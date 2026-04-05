"""Browser-use Cloud client — runs browsing agents on browser-use's
hosted infrastructure instead of launching a local Chromium.

When ``settings.browser_use_api_key`` is set, every scraper (scan runner,
competitor front-page, competitor checkout walk) routes through this
module. The cloud runs the LLM that drives the agent (picked via
``settings.browser_use_cloud_model``) so no Anthropic tokens are burned
on action selection — our Anthropic key is only used for the
non-browsing Claude calls (discovery, synthesis, findings analysis).

Streams per-step reasoning into scan_log exactly like the local path so
the UI looks the same from the caller's perspective.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from src.config.settings import settings

from ..observability import scan_log

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Terminal cloud statuses per the SDK's TaskStatus literal.
_TERMINAL_STATUSES = {"finished", "stopped", "error", "paused"}


class CloudAgentError(RuntimeError):
    """Raised when the cloud task cannot produce usable structured output."""


def cloud_enabled() -> bool:
    """True when we have a non-placeholder browser-use API key.

    Real keys start with the ``bu_`` prefix (per browser-use docs); anything
    else (empty, ``your-...-here``, ``demo``, random junk) is treated as
    not-configured and we fall back to local.
    """
    key = (settings.browser_use_api_key or "").strip()
    if not key or key.lower() == "demo":
        return False
    if key.startswith("bu_xxxxx"):
        return False
    if not key.startswith("bu_"):
        return False
    return True


def _clamp(s: Any, n: int) -> str:
    return str(s or "")[:n]


# Prose-ish keys a cloud model might use to wrap its real reasoning in
# a JSON envelope. We prefer them in this order when humanizing.
_REASONING_KEYS = (
    "thinking", "thought", "reasoning", "rationale",
    "next_goal", "goal", "plan",
    "evaluation_previous_goal", "evaluation",
    "summary", "memory", "observation", "text",
)


def _humanize(s: Any, limit: int = 300) -> str:
    """Coerce a cloud-agent text field into readable prose.

    Some browser-use cloud models emit ``next_goal`` / ``evaluation`` /
    ``memory`` as JSON envelopes (``{"thinking": "…", "action": "…"}``)
    rather than plain strings. When that happens we unwrap to the
    longest useful string value inside the envelope. Plain text passes
    through unchanged.
    """
    raw = str(s or "").strip()
    if not raw:
        return ""
    if raw[0] not in "{[":
        return raw[:limit]
    try:
        obj = json.loads(raw)
    except Exception:  # noqa: BLE001
        return raw[:limit]

    def _extract(node: Any, depth: int = 0) -> str:
        if depth > 3:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            parts = [p for p in (_extract(x, depth + 1) for x in node) if p]
            return " · ".join(parts)
        if isinstance(node, dict):
            # Prefer well-known reasoning keys in priority order.
            for k in _REASONING_KEYS:
                if k in node:
                    v = _extract(node[k], depth + 1)
                    if v:
                        return v
            # Otherwise take the longest string-ish descendant.
            best = ""
            for v in node.values():
                cand = _extract(v, depth + 1)
                if len(cand) > len(best):
                    best = cand
            return best
        return ""

    out = _extract(obj).strip()
    return (out or raw)[:limit]


def _action_name(a: Any) -> str:
    """Extract a readable action name from a cloud SDK action entry.

    Cloud agent steps carry ``actions`` as dicts of the form
    ``{"click_element": {"index": 5}}`` — the key is the action name,
    the value is its parameters. Pydantic tools may also return objects
    with ``model_dump``. Fall back to the string form for anything
    else. Returns the name only — never the JSON blob — so the scanner
    sidebar shows readable tokens instead of stringified dicts.
    """
    if isinstance(a, str):
        # Cloud SDK's TaskStepView emits each action as a stringified
        # JSON blob like '{"click": {"index": 831}}'. Parse it and pull
        # the first key (the action name) so the sidebar shows
        # "click" instead of the whole JSON object.
        s = a.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
            except Exception:  # noqa: BLE001
                obj = None
            if isinstance(obj, dict):
                for k in obj.keys():
                    return str(k)[:40]
        return s[:40]
    if isinstance(a, dict):
        for k in a.keys():
            return str(k)[:40]
        return ""
    dump = getattr(a, "model_dump", None)
    if callable(dump):
        try:
            d = dump(exclude_unset=True)
        except Exception:  # noqa: BLE001
            d = None
        if isinstance(d, dict):
            for k in d.keys():
                return str(k)[:40]
    name = getattr(a, "name", None) or getattr(a, "type", None)
    if name:
        return str(name)[:40]
    return str(a)[:40]


async def run_cloud_agent(
    *,
    task: str,
    schema: Type[T],
    start_url: str,
    max_steps: int = 10,
    scan_id: Optional[str] = None,
    step_offset: int = 0,
    timeout_s: float = 300.0,
    llm: Optional[str] = None,
    allowed_domains: Optional[list[str]] = None,
    vision: Any = False,
    judge: bool = False,
    skill_ids: Optional[list[str]] = None,
    lane: str = "",
) -> T:
    """Submit a task to browser-use cloud and stream reasoning to scan_log.

    Returns the parsed pydantic output. Raises :class:`CloudAgentError`
    when the task ends in any non-``finished`` status or the wall-clock
    timeout trips. Callers wrap this in their own demo/fallback logic.
    """
    # Import inside the function so the rest of the process boots even
    # without browser-use-sdk installed.
    from browser_use_sdk import AsyncBrowserUse  # type: ignore

    client = AsyncBrowserUse(api_key=settings.browser_use_api_key)
    try:
        create_kwargs: dict[str, Any] = {
            "task": task,
            "llm": llm or settings.browser_use_cloud_model,
            "start_url": start_url,
            "max_steps": max_steps,
            "schema": schema,
            "allowed_domains": allowed_domains,
            # Vision-on unlocks the cloud agent's built-in CAPTCHA solving
            # + visual cart/checkout layout parsing. Default off (cheaper)
            # for simple observation tasks like page-summary scans.
            "vision": vision,
        }
        if judge:
            # Second-pass LLM validates extracted fields before returning.
            # Cuts "reached_checkout=true with everything null" snapshots.
            create_kwargs["judge"] = True
        if skill_ids:
            # Pre-recorded skill playback → deterministic clicks without
            # LLM reasoning on steps the skill covers.
            create_kwargs["skill_ids"] = skill_ids
        created = await client.tasks.create_task(**create_kwargs)
    except Exception as e:  # noqa: BLE001
        # Loudest diagnostic path: auth rejections, quota, 4xx. Include the
        # class name so an expired key doesn't silently degrade to demo data.
        msg = str(e)
        if any(
            token in msg.lower()
            for token in ("unauthorized", "forbidden", "401", "403", "invalid api key")
        ):
            log.error(
                "browser-use Cloud rejected the API key (%s: %s) — check "
                "BROWSER_USE_API_KEY in .env",
                type(e).__name__, msg,
            )
        raise CloudAgentError(
            f"cloud create_task failed: {type(e).__name__}: {msg}"
        ) from e

    task_id = getattr(created, "id", None) or getattr(created, "task_id", "?")
    session_id = getattr(created, "session_id", None) or ""

    # Resolve the live_url so the UI can link out to the running session.
    # Skipped when there's no scan_id to emit into. Wrapped in a 5s
    # timeout so a slow sessions endpoint can't wedge task startup.
    live_url = ""
    if session_id and scan_id:
        try:
            sess = await asyncio.wait_for(
                client.sessions.get_session(session_id),
                timeout=5.0,
            )
            raw = getattr(sess, "live_url", "") or ""
            # Only pass through http(s) URLs — the string is rendered as
            # an <a href> in the extension popup. Reject javascript:,
            # data:, etc. even though browser-use shouldn't emit them.
            if isinstance(raw, str) and raw.startswith(("https://", "http://")):
                live_url = raw[:2048]
        except asyncio.TimeoutError:
            log.info(
                "cloud task %s live_url fetch timed out", task_id,
            )
        except Exception as e:  # noqa: BLE001
            log.info(
                "cloud task %s session fetch failed: %s", task_id, e,
            )

    if scan_id:
        scan_log.append(
            scan_id,
            {
                "step": step_offset,
                "source": "browser-use",
                "lane": lane,
                "live_url": live_url,
                "next_goal": f"cloud task started (id={task_id})",
                "evaluation": start_url,
            },
        )

    last_seen = 0
    final_snapshot = None

    async def _watch() -> Any:
        nonlocal last_seen, final_snapshot
        async for snapshot in created.watch(interval=2.0):
            # Stream each new step into scan_log as it appears cloud-side.
            steps = getattr(snapshot, "steps", None) or []
            for step in steps[last_seen:]:
                if scan_id:
                    scan_log.append(
                        scan_id,
                        {
                            "step": int(getattr(step, "number", 0)) + step_offset,
                            "source": "browser-use",
                            "lane": lane,
                            "evaluation": _humanize(
                                getattr(step, "evaluation_previous_goal", ""), 300
                            ),
                            "memory": _humanize(getattr(step, "memory", ""), 300),
                            "next_goal": _humanize(
                                getattr(step, "next_goal", ""), 300
                            ),
                            "actions": [
                                _action_name(a)
                                for a in (
                                    getattr(step, "actions", []) or []
                                )[:3]
                            ],
                        },
                    )
            last_seen = len(steps)
            if getattr(snapshot, "status", None) in _TERMINAL_STATUSES:
                final_snapshot = snapshot
                return
        return

    finished_normally = False
    try:
        await asyncio.wait_for(_watch(), timeout=timeout_s)
        finished_normally = True
    except asyncio.TimeoutError as e:
        raise CloudAgentError(
            f"cloud task {task_id} exceeded wall-clock cap {timeout_s}s"
        ) from e
    finally:
        # Any non-normal exit (timeout, asyncio cancellation, exception
        # mid-watch) leaves the cloud task billing until max_steps unless
        # we explicitly stop it. Fire and forget — never let cleanup mask
        # the original exception.
        if not finished_normally:
            try:
                await client.tasks.update_task(
                    task_id=task_id, action="stop_task_and_session",
                )
            except Exception as stop_err:  # noqa: BLE001
                log.info(
                    "cloud task %s stop request failed: %s", task_id, stop_err,
                )

    if final_snapshot is None:
        raise CloudAgentError(f"cloud task {task_id} produced no final snapshot")

    # Surface cost for every finished run so billing is visible in logs.
    cost = getattr(final_snapshot, "cost", None)
    if cost:
        log.info("cloud task %s finished: cost=%s", task_id, cost)

    status = getattr(final_snapshot, "status", "unknown")
    if status != "finished":
        raise CloudAgentError(
            f"cloud task {task_id} ended with status={status}"
        )

    parsed = getattr(final_snapshot, "parsed_output", None)
    if parsed is None:
        raise CloudAgentError(
            f"cloud task {task_id} finished without parsed output"
        )
    return parsed  # type: ignore[return-value]
