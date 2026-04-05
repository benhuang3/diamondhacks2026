"""Shared JSON-extraction helpers for Claude-emitted text.

Claude doesn't always return clean JSON — it may wrap the payload in
```json fences``` or include surrounding prose. These helpers pull the
first well-formed object/array out of a text blob without raising.
"""

from __future__ import annotations

import json
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first JSON object in ``text`` or ``None``.

    Tries fenced ```json``` blocks first, then falls back to the first
    balanced ``{...}`` span. Never raises.
    """
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                try:
                    return json.loads(p)
                except Exception:  # noqa: BLE001
                    continue
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def extract_json_array(text: str) -> list[dict[str, Any]]:
    """Return the first JSON array in ``text`` or an empty list. Never raises."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("["):
                try:
                    return json.loads(p)
                except Exception:  # noqa: BLE001
                    continue
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            return []
    return []
