"""Thin async wrapper around the Anthropic SDK.

DEMO_MODE (no/placeholder key) is handled by the caller; this client simply
exposes `is_demo_mode()` and a `complete()` method that returns plain text.
Failures fall through to a `DemoFallbackError` so callers can degrade.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from src.config.settings import settings

from ..observability.metrics import metrics

log = logging.getLogger(__name__)


class DemoFallbackError(RuntimeError):
    """Raised when a real Claude call fails and we should fall back to demo output."""


def is_demo_mode() -> bool:
    if settings.demo_mode:
        return True
    key = settings.anthropic_api_key or ""
    return (not key) or key.startswith("sk-ant-xxxxx") or key.lower() == "demo"


class ClaudeClient:
    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or settings.anthropic_model
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # type: ignore
        except Exception as e:  # pragma: no cover
            raise DemoFallbackError(f"anthropic SDK not installed: {e}")
        try:
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        except Exception as e:  # pragma: no cover
            raise DemoFallbackError(f"failed to init anthropic client: {e}")
        return self._client

    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        if is_demo_mode():
            raise DemoFallbackError("DEMO_MODE active")

        def _call() -> str:
            client = self._get_client()
            kwargs = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            msg = client.messages.create(**kwargs)
            # extract text
            parts = []
            for block in getattr(msg, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()

        metrics.inc("claude_calls_total", model=self.model)
        try:
            return await asyncio.to_thread(_call)
        except DemoFallbackError:
            raise
        except Exception as e:  # noqa: BLE001
            metrics.inc("claude_call_failures_total", model=self.model)
            log.warning("Claude call failed, falling back to demo: %s", e)
            raise DemoFallbackError(str(e)) from e

    async def stream_complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        on_text: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Like :meth:`complete`, but invokes ``on_text`` with the
        accumulated text after every stream chunk.

        ``on_text`` runs in the worker thread (via ``asyncio.to_thread``)
        and MUST NOT raise — any exception is swallowed so streaming
        never corrupts the final completion result.
        """
        if is_demo_mode():
            raise DemoFallbackError("DEMO_MODE active")

        def _call() -> str:
            client = self._get_client()
            kwargs = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            parts: list[str] = []
            with client.messages.stream(**kwargs) as stream:
                for chunk in stream.text_stream:
                    if chunk:
                        parts.append(chunk)
                        if on_text is not None:
                            try:
                                on_text("".join(parts))
                            except Exception:  # noqa: BLE001
                                pass
            return "".join(parts).strip()

        metrics.inc("claude_calls_total", model=self.model)
        try:
            return await asyncio.to_thread(_call)
        except DemoFallbackError:
            raise
        except Exception as e:  # noqa: BLE001
            metrics.inc("claude_call_failures_total", model=self.model)
            log.warning("Claude stream failed, falling back to demo: %s", e)
            raise DemoFallbackError(str(e)) from e
