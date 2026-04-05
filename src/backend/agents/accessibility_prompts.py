"""Prompt templates for accessibility / UX scan analysis."""

SYSTEM_SCAN = (
    "You are an accessibility and UX reviewer for ecommerce storefronts. "
    "Given a page snapshot (interactive elements, images, contrast hints), "
    "produce concrete findings: severity, category, selector, title, description, suggestion. "
    "Be specific and actionable."
)

SCAN_FINDINGS_PROMPT = """\
Analyze this storefront page snapshot and return 5-15 findings as JSON.

URL: {url}
Title: {title}
Interactive elements: {elements}
Missing alt images: {missing_alt}
Low contrast count: {low_contrast}

Return a JSON array. Each finding must have keys:
- selector (string, CSS selector)
- severity ("high"|"medium"|"low")
- category ("a11y"|"ux"|"contrast"|"nav")
- title (short)
- description (1-2 sentences)
- suggestion (actionable)
"""

SCAN_FINDINGS_PROMPT_PER_PAGE = """\
Analyze this storefront page snapshot and return 3-15 findings as JSON.

URL: {url}
Page kind: {kind}
Title: {title}
Interactive elements: {elements}
Missing alt images: {missing_alt}
Low contrast count: {low_contrast}

Tailor findings to this page's role (home/category/product/cart/other).
Return a JSON array. Each finding must have keys:
- selector (string, CSS selector)
- severity ("high"|"medium"|"low")
- category ("a11y"|"ux"|"contrast"|"nav")
- title (short)
- description (1-2 sentences)
- suggestion (actionable)
"""

SYSTEM_FIX_FINDING = (
    "You generate MINIMAL, SAFE DOM patches that fix one accessibility or "
    "UX finding at a time. You must return ONE of four operation kinds: "
    "'css' (rule injection), 'attribute' (set a single attribute), "
    "'class' (add class tokens), or 'none' (refuse, with a short reason). "
    "Never emit 'text' or 'html' operations. Never touch src, href, style, "
    "or any on* event attribute. Never use javascript:, data:, or vbscript: "
    "URIs anywhere in the output. When no safe DOM-only fix exists (e.g. "
    "the finding requires JavaScript, server changes, or restructuring), "
    "return {\"kind\": \"none\", \"reason\": \"...\"}. "
    "Respond with STRICT JSON only — no prose, no markdown fences."
)

FIX_FINDING_PROMPT = """\
Produce the minimal DOM patch that fixes this finding.

Finding:
  title: {title}
  severity: {severity}
  category: {category}
  selector: {selector}
  description: {description}
  suggestion: {suggestion}

Pick the safest operation kind:
  - contrast issues, focus rings, spacing → "css" (one or more CSS rules)
  - missing alt / aria-label / aria-* / title / lang / role → "attribute"
  - need to add a utility classname (visual-only) → "class"
  - no safe DOM-only fix (needs JS, server work, copy rewrite) → "none"

Return a JSON object with this exact shape (fields not relevant to the
chosen kind must be omitted):
  {{"kind": "css", "rules": "selector {{ prop: value; ... }}"}}
  {{"kind": "attribute", "selector": "...", "name": "alt|aria-*|title|lang|role|tabindex", "value": "..."}}
  {{"kind": "class", "selector": "...", "classes": "classA classB"}}
  {{"kind": "none", "reason": "short explanation"}}

STRICT RULES — violating any of these will make your output be rejected:
- The 'name' for attribute MUST match: alt, title, lang, role, tabindex, or aria-<name>.
- No javascript:/data:/vbscript:/file: URIs anywhere in the output.
- No @import, no expression(), no <script in CSS rules.
- Classnames must match /^[A-Za-z_][A-Za-z0-9_-]{{0,63}}$/, at most 5 tokens.
- Attribute values must not start with javascript:/data:/vbscript:.
- CSS rules MUST NOT use any of: the `position` property (fixed/sticky/absolute/relative), `inset`, `z-index`, `pointer-events`, `100vw`, `100vh`, or the `::before`/`::after` pseudo-elements. These create page-blocking overlays.
- CSS property allowlist (anything else is rejected): `outline*`, `border*`, `background*`, `color`, `box-shadow` (inset only), `text-decoration*`, `padding*`, `margin*`, `font-weight`, `font-style`. No `width`, `height`, `min-*`, `max-*`, `display`, `opacity`, `transform`, `filter`.
- CSS selectors MUST NOT be a bare `body`, `html`, `:root`, or `*` (those repaint the entire page). Scope every rule to the finding's own selector or a descendant of it.

Return STRICT JSON only.
"""

SCAN_REPORT_PROMPT = """\
Given these scan findings for {url}, write a short markdown executive summary,
propose 3 scores 0-100 for accessibility/ux/flow, 2-4 sections with titles and
markdown body, and 3-5 recommendations.

Findings:
{findings}
"""
