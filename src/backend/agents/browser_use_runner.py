"""Page-summary runner built on the browser-use SDK.

The SDK drives a real browser via CDP and has an LLM agent reason about the
page. For our needs we give it a bounded observational task and pull a
structured `PageSummary` back via `extraction_schema`/`output_model_schema`.

In DEMO_MODE (or any failure) we return a canned snapshot so the rest of
the pipeline keeps working without keys or network.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.config.settings import settings

from ..observability import scan_log
from .browser_use_cloud import CloudAgentError, cloud_enabled, run_cloud_agent

log = logging.getLogger(__name__)

# Agents spawn a real Chromium per run. Cap concurrency so a burst of
# /scan requests doesn't fork N browsers on the box.
_MAX_CONCURRENT_AGENTS = 2
_agent_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_AGENTS)

# Wall-clock cap on a single agent run (navigate + observe + done).
_AGENT_WALL_CLOCK_SECONDS = 90.0

# Field-length caps applied to agent-returned content before it flows
# into downstream Claude prompts or the DB.
_MAX_TITLE_LEN = 200
_MAX_SELECTOR_LEN = 200
_MAX_TEXT_LEN = 120
_MAX_ELEMENTS = 20


def _clamp(s: Any, n: int) -> str:
    return str(s or "")[:n]


# --- Structured output schema the agent is asked to fill ------------------

class _InteractiveElement(BaseModel):
    tag: str = Field(..., description="HTML tag, e.g. 'button', 'a', 'input', 'img'")
    selector: str = Field(..., description="Best CSS selector for the element")
    text: str = Field(default="", description="Visible label or alt text, <=80 chars")


class _PageSummary(BaseModel):
    title: str = Field(default="")
    interactive_elements: list[_InteractiveElement] = Field(default_factory=list)
    missing_alt_images: int = Field(default=0)
    low_contrast_count: int = Field(default=0)


# --- Demo fallback --------------------------------------------------------

DEMO_SNAPSHOT: dict[str, Any] = {
    "title": "Demo Storefront",
    "interactive_elements": [
        {"tag": "button", "selector": "button.checkout-btn", "text": "Checkout"},
        {"tag": "a", "selector": "a.nav-link", "text": "Shop"},
        {"tag": "input", "selector": "input#search", "text": ""},
        {"tag": "img", "selector": "img.hero", "text": ""},
        {"tag": "button", "selector": "button.add-to-cart", "text": "Add to cart"},
    ],
    "missing_alt_images": 3,
    "low_contrast_count": 2,
}


def _is_demo_key() -> bool:
    key = settings.anthropic_api_key or ""
    return (not key) or key.startswith("sk-ant-xxxxx") or key.lower() == "demo"


# --- browser-use Agent path -----------------------------------------------

def _make_step_callback(scan_id: Optional[str]):
    """Return a callback the Agent fires after each step that records the
    reasoning chain into scan_log for the given scan_id."""
    if not scan_id:
        return None

    def _callback(_state, output, step_num: int) -> None:
        # AgentOutput fields: evaluation_previous_goal, memory, next_goal, action
        actions = []
        for a in getattr(output, "action", None) or []:
            dump = a.model_dump(exclude_unset=True) if hasattr(a, "model_dump") else {}
            for name in dump.keys():
                actions.append(name)
                break
        entry = {
            "step": int(step_num),
            "source": "browser-use",
            "evaluation": _clamp(getattr(output, "evaluation_previous_goal", "") or "", 300),
            "memory": _clamp(getattr(output, "memory", "") or "", 300),
            "next_goal": _clamp(getattr(output, "next_goal", "") or "", 300),
            "actions": actions[:3],
        }
        scan_log.append(scan_id, entry)

    return _callback


async def _run_browser_use_agent(
    url: str, timeout_ms: int, *, scan_id: Optional[str] = None
) -> dict[str, Any]:
    """Use browser-use's Agent to visit `url` and extract a structured summary.

    Raises on any failure so the caller can fall back. Caller is responsible
    for DEMO_MODE short-circuiting.
    """
    # Imports inside the function so missing optional deps don't blow up at
    # module import time.
    from browser_use import Agent, BrowserProfile  # type: ignore
    from browser_use.llm import ChatAnthropic  # type: ignore

    task = (
        f"Navigate to {url} and observe the page. Do not click, do not "
        "submit any forms, do not navigate away. Return a structured summary "
        "with: the page title; up to 15 interactive elements "
        "(button, a, input, img) including their tag, a CSS selector, and "
        "visible text (<=80 chars); the count of <img> elements that are "
        "missing an alt attribute."
    )

    llm = ChatAnthropic(
        model=settings.anthropic_model,  # type: ignore[arg-type]
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
        timeout=timeout_ms / 1000.0,
    )

    # Run Chromium headless by default so scanning from the extension/web
    # doesn't pop a visible window on the user's desktop.
    profile = BrowserProfile(headless=settings.browser_use_headless)

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=profile,
        output_model_schema=_PageSummary,
        use_vision=False,
        enable_planning=False,
        use_judge=False,
        use_thinking=False,
        max_actions_per_step=2,
        directly_open_url=True,
        register_new_step_callback=_make_step_callback(scan_id),
    )

    history = await asyncio.wait_for(
        agent.run(max_steps=6),
        timeout=_AGENT_WALL_CLOCK_SECONDS,
    )
    parsed: Optional[_PageSummary] = history.get_structured_output(_PageSummary)
    if parsed is None:
        raise RuntimeError("browser-use agent returned no structured output")

    elements = [
        {
            "tag": _clamp(e.tag, 16),
            "selector": _clamp(e.selector, _MAX_SELECTOR_LEN),
            "text": _clamp(e.text, _MAX_TEXT_LEN),
        }
        for e in parsed.interactive_elements[:_MAX_ELEMENTS]
    ]
    return {
        "url": url,
        "title": _clamp(parsed.title, _MAX_TITLE_LEN),
        "interactive_elements": elements,
        "missing_alt_images": max(0, int(parsed.missing_alt_images)),
        "low_contrast_count": max(0, int(parsed.low_contrast_count)),
    }


# --- Public entry point ---------------------------------------------------

async def fetch_page_summary(
    url: str,
    *,
    scan_id: Optional[str] = None,
    timeout_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Return a dict summary of interactive elements on the page.

    Never raises — always returns something usable. Demo snapshot is used
    when there is no Anthropic key, when the browser-use SDK isn't present,
    or when the agent run fails.
    """
    timeout_ms = timeout_ms or settings.browser_use_timeout_ms
    snapshot = dict(DEMO_SNAPSHOT)
    snapshot["url"] = url

    if settings.demo_mode or _is_demo_key():
        return snapshot

    # Prefer browser-use Cloud when an API key is configured — the cloud
    # runs the agent's LLM too, so our Anthropic quota stays for discovery
    # / synthesis / findings Claude calls.
    if cloud_enabled():
        try:
            task = (
                f"Navigate to {url} and observe the page. Do not click, do not "
                "submit any forms, do not navigate away. Return a structured "
                "summary with: the page title; up to 15 interactive elements "
                "(button, a, input, img) including their tag, a CSS selector, "
                "and visible text (<=80 chars); the count of <img> elements "
                "that are missing an alt attribute."
            )
            parsed = await run_cloud_agent(
                task=task,
                schema=_PageSummary,
                start_url=url,
                max_steps=6,
                scan_id=scan_id,
                timeout_s=_AGENT_WALL_CLOCK_SECONDS,
            )
            elements = [
                {
                    "tag": _clamp(e.tag, 16),
                    "selector": _clamp(e.selector, _MAX_SELECTOR_LEN),
                    "text": _clamp(e.text, _MAX_TEXT_LEN),
                }
                for e in parsed.interactive_elements[:_MAX_ELEMENTS]
            ]
            return {
                "url": url,
                "title": _clamp(parsed.title, _MAX_TITLE_LEN),
                "interactive_elements": elements,
                "missing_alt_images": max(0, int(parsed.missing_alt_images)),
                "low_contrast_count": max(0, int(parsed.low_contrast_count)),
            }
        except CloudAgentError as e:
            log.warning("cloud scan agent failed for %s, using demo snapshot: %s", url, e)
            return snapshot
        except Exception as e:  # noqa: BLE001
            log.warning("cloud scan agent exception for %s, using demo snapshot: %s", url, e)
            return snapshot

    # --- Local fallback (no cloud key configured) ---
    try:
        if scan_id:
            scan_log.append(
                scan_id,
                {"step": 0, "source": "browser-use", "next_goal": "launching browser…"},
            )
        async with _agent_semaphore:
            return await _run_browser_use_agent(url, timeout_ms, scan_id=scan_id)
    except ImportError as e:
        log.warning("browser-use SDK unavailable, using demo snapshot: %s", e)
    except asyncio.TimeoutError:
        log.warning(
            "browser-use agent exceeded %.0fs for %s, using demo snapshot",
            _AGENT_WALL_CLOCK_SECONDS, url,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("browser-use agent failed for %s, using demo snapshot: %s", url, e)
    return snapshot
