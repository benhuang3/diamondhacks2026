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

SCAN_REPORT_PROMPT = """\
Given these scan findings for {url}, write a short markdown executive summary,
propose 3 scores 0-100 for accessibility/ux/flow, 2-4 sections with titles and
markdown body, and 3-5 recommendations.

Findings:
{findings}
"""
