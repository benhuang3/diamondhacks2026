"""Strict allowlist validator for :class:`FixOperation` payloads.

Rejects — does not sanitize. Anything that doesn't match the allowlist
is turned into a ``kind="none"`` operation with a reason the frontend
renders inline. The validator is the only thing standing between
Claude-generated text and a DOM-mutating API response, so it errs
heavily on the side of refusal.
"""

from __future__ import annotations

import re
from typing import Any

from ..models.scan import FixOperation

_MAX_SELECTOR_LEN = 500
_MAX_RULES_LEN = 2000
_MAX_VALUE_LEN = 500
_MAX_CLASSES = 5

# Attributes we're willing to set from a Claude-generated fix. Locked
# down to accessibility + presentational attrs — no src/href/onXXX/style.
_ALLOWED_ATTRS_RE = re.compile(
    r"^(alt|title|lang|role|tabindex|aria-[a-z][a-z0-9-]*)$",
)
# Single CSS-classname token (CSS ident-ish): letter/underscore start,
# then alnum/underscore/dash, up to 64 chars.
_CLASSNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
# Selectors we allow: ASCII printable only. Rejects control chars + most
# obvious injection fingerprints. The real guarantee comes from the
# browser's own CSS-selector parser, not from us trying to pre-validate.
_SELECTOR_CHARS_RE = re.compile(r"^[A-Za-z0-9 #.\-_:>+~\[\]='\"*,()\\/]+$")

# Dangerous fingerprints rejected wherever they appear in a payload.
_DANGEROUS_URI_PREFIXES = ("javascript:", "data:", "vbscript:", "file:")

# CSS properties we let Claude emit. Anything else is a refusal. The
# prompt already enumerates this list; the validator enforces it so a
# hallucinated `width: 100%; height: 100%; background: red` on `body`
# can't paint a full-screen cover. Prefixes are matched by equality or
# with a trailing dash (so `border-color` passes under `border`).
_ALLOWED_CSS_PROP_PREFIXES = (
    "outline",
    "border",
    "background",
    "color",
    "box-shadow",
    "text-decoration",
    "padding",
    "margin",
    "font-weight",
    "font-style",
)

# Bare selectors that target the entire page. Compound selectors like
# `body .sr-scope` are fine — only reject when the selector IS one of
# these tokens. A full-page `background`/`color` rule repaints the
# whole viewport even without any positioning.
_FORBIDDEN_BARE_SELECTORS = {"body", "html", ":root", "*"}
_DANGEROUS_CSS_TOKENS = (
    "@import",
    "expression(",
    "javascript:",
    "vbscript:",
    "behavior:",
    "<script",
    # Any positioning is dangerous in a Claude-generated accessibility
    # patch — outlines, borders, backgrounds, and contrast fixes never
    # need `position`, so block the property entirely. This also kills
    # fixed/sticky/absolute overlays that combine with inset:0 or
    # 100vw/100vh sizing to cover the page and trap the user.
    "position:",
    "position :",
    # `inset` is the shorthand for top/right/bottom/left — combined
    # with any positioning it paints a full-viewport box.
    "inset:",
    "inset :",
    # Viewport-sized rules — almost always indicate a full-screen overlay.
    "100vw",
    "100vh",
    # Blocks all pointer-events manipulation — Claude-written fixes
    # should never need this, and getting it wrong traps user input.
    "pointer-events",
    # Pseudo-element content injection is the other overlay vector
    # (::before/::after with sizing). Accessibility fixes don't need it.
    "::before",
    "::after",
    # Extreme z-index stacks things above the sidebar / modal / content.
    "z-index",
)


def _none(reason: str) -> FixOperation:
    return FixOperation(kind="none", reason=reason)


def _has_dangerous_uri(s: str) -> bool:
    low = s.strip().lower()
    return any(low.startswith(p) for p in _DANGEROUS_URI_PREFIXES)


def _css_has_dangerous_token(s: str) -> bool:
    low = s.lower()
    return any(tok in low for tok in _DANGEROUS_CSS_TOKENS)


def _css_declared_properties(rules: str) -> list[str]:
    """Return lowercase property names declared inside all ``{...}`` blocks.

    Ignores content outside braces (selectors, comments) so `[color=x]`
    attribute selectors don't get counted as declarations.
    """
    props: list[str] = []
    for block in re.finditer(r"\{([^{}]*)\}", rules):
        for decl in block.group(1).split(";"):
            if ":" not in decl:
                continue
            name = decl.split(":", 1)[0].strip().lower()
            if name:
                props.append(name)
    return props


def _css_property_allowed(name: str) -> bool:
    return any(
        name == p or name.startswith(p + "-")
        for p in _ALLOWED_CSS_PROP_PREFIXES
    )


def _css_selectors(rules: str) -> list[str]:
    """Extract the top-level selector for each ``selector { ... }`` block."""
    sels: list[str] = []
    for match in re.finditer(r"([^{}]*)\{", rules):
        for sel in match.group(1).split(","):
            s = sel.strip()
            if s:
                sels.append(s)
    return sels


_MAX_LENGTH_PX = 200
# Numeric length tokens: capture number + unit. Used to bound
# padding/border/box-shadow so a 9999px spread can't paint a
# viewport-covering overlay on top of an otherwise-allowlisted rule.
_LENGTH_TOKEN_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(px|pt|em|rem|vh|vw|%)",
    re.IGNORECASE,
)
_LENGTH_LIMITS = {
    "px": _MAX_LENGTH_PX,
    "pt": _MAX_LENGTH_PX,  # ~1:1 for our purposes
    "em": 20.0,
    "rem": 20.0,
    "vh": 20.0,
    "vw": 20.0,
    "%": 100.0,
}


def _css_lengths_in_bounds(rules: str) -> tuple[bool, str]:
    """Reject any length literal that exceeds a sane per-unit cap.

    Stops spread-radius overlays (``box-shadow: 0 0 0 9999px red``) and
    runaway padding/border inflation (``border: 9999px solid red``)
    without having to special-case each property.
    """
    for m in _LENGTH_TOKEN_RE.finditer(rules):
        val = abs(float(m.group(1)))
        unit = m.group(2).lower()
        cap = _LENGTH_LIMITS.get(unit)
        if cap is not None and val > cap:
            return False, f"{m.group(0)} exceeds the {unit} length cap"
    return True, ""


def _box_shadows_are_inset(rules: str) -> tuple[bool, str]:
    """Require every ``box-shadow`` declaration to be inset-only.

    Non-inset shadows paint outside the element — combined with any
    reasonable spread radius they can cover sibling content, and we
    don't need outer shadows for accessibility fixes.
    """
    for block in re.finditer(r"\{([^{}]*)\}", rules):
        for decl in block.group(1).split(";"):
            if ":" not in decl:
                continue
            name, _, value = decl.partition(":")
            if name.strip().lower() != "box-shadow":
                continue
            if "inset" not in value.lower():
                return False, "box-shadow must use the 'inset' keyword"
    return True, ""


def _css_url_is_safe(rules: str) -> bool:
    """Walk url(...) tokens and reject any that point at javascript:/data:/etc.

    Relative or https(s) external assets are permitted. Anything with a
    suspicious scheme fails. url() arguments may be quoted or unquoted."""
    for match in re.finditer(r"url\(\s*([^)]+?)\s*\)", rules, re.IGNORECASE):
        arg = match.group(1).strip().strip("'\"")
        if _has_dangerous_uri(arg):
            return False
    return True


def _valid_selector(sel: str | None) -> bool:
    if not sel:
        return False
    if len(sel) > _MAX_SELECTOR_LEN:
        return False
    if "\x00" in sel or "\n" in sel or "\r" in sel:
        return False
    return bool(_SELECTOR_CHARS_RE.fullmatch(sel))


def validate_fix_operation(raw: dict[str, Any] | None) -> FixOperation:
    """Coerce a dict (likely Claude-parsed) into a validated FixOperation.

    Returns ``FixOperation(kind="none", reason=...)`` on any rule
    violation. The resulting instance is always API-safe: frontend code
    can apply it to the DOM without extra sanitization.
    """
    if not isinstance(raw, dict):
        return _none("fix generator returned no usable operation")

    kind = str(raw.get("kind") or "").strip().lower()

    if kind == "none":
        reason = str(raw.get("reason") or "no safe DOM-only fix available").strip()
        return FixOperation(kind="none", reason=reason[:240])

    if kind == "css":
        rules = raw.get("rules")
        if not isinstance(rules, str) or not rules.strip():
            return _none("css fix missing rules")
        if len(rules) > _MAX_RULES_LEN:
            return _none("css rules too long")
        if "\x00" in rules:
            return _none("css rules contain control characters")
        if _css_has_dangerous_token(rules):
            return _none("css rules contain disallowed token")
        if not _css_url_is_safe(rules):
            return _none("css url() points at unsafe scheme")
        for sel in _css_selectors(rules):
            if sel.lower() in _FORBIDDEN_BARE_SELECTORS:
                return _none(f"css selector '{sel}' targets the entire page")
        declared = _css_declared_properties(rules)
        if not declared:
            return _none("css rules declare no properties")
        for prop in declared:
            if not _css_property_allowed(prop):
                return _none(f"css property '{prop}' is not allowlisted")
        ok, why = _css_lengths_in_bounds(rules)
        if not ok:
            return _none(why)
        ok, why = _box_shadows_are_inset(rules)
        if not ok:
            return _none(why)
        return FixOperation(kind="css", rules=rules.strip())

    if kind == "attribute":
        selector = raw.get("selector")
        name = raw.get("name")
        value = raw.get("value")
        if not isinstance(selector, str) or not _valid_selector(selector):
            return _none("attribute fix has invalid selector")
        if not isinstance(name, str) or not _ALLOWED_ATTRS_RE.fullmatch(name):
            return _none(f"attribute '{name}' is not allowlisted")
        if not isinstance(value, str):
            return _none("attribute fix missing value")
        if len(value) > _MAX_VALUE_LEN:
            return _none("attribute value too long")
        if _has_dangerous_uri(value):
            return _none("attribute value points at unsafe scheme")
        # Strip control chars — leave unicode alone.
        cleaned_value = "".join(c for c in value if c == " " or c >= " ")
        return FixOperation(
            kind="attribute",
            selector=selector.strip(),
            name=name.strip().lower(),
            value=cleaned_value,
        )

    if kind == "class":
        selector = raw.get("selector")
        classes = raw.get("classes")
        if not isinstance(selector, str) or not _valid_selector(selector):
            return _none("class fix has invalid selector")
        if not isinstance(classes, str) or not classes.strip():
            return _none("class fix missing classes")
        tokens = [t for t in classes.split() if t]
        if not tokens:
            return _none("class fix has no tokens")
        if len(tokens) > _MAX_CLASSES:
            return _none("class fix has too many tokens")
        for t in tokens:
            if not _CLASSNAME_RE.fullmatch(t):
                return _none(f"class token '{t}' is invalid")
        return FixOperation(
            kind="class",
            selector=selector.strip(),
            classes=" ".join(tokens),
        )

    return _none(f"unknown fix kind: {kind!r}")
