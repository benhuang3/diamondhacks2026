"""Prompt templates for competitor discovery + pricing comparison."""

SYSTEM_COMPETITORS = (
    "You are an ecommerce competitive analyst. Given a store URL and optional product hint, "
    "propose 3-5 competitor store URLs selling similar products. "
    "Then analyze their pricing/shipping/deals."
)

COMPETITOR_DISCOVERY_PROMPT = """\
Store: {store_url}
Product hint: {product_hint}
Custom prompt: {custom_prompt}

List 3-5 competitor stores selling similar products. Return JSON array of objects:
- name (string)
- url (string, https://)
- rationale (short)
"""

COMPETITOR_REPORT_PROMPT = """\
Given these competitor pricing results for {store_url}, write a markdown summary,
propose 3 scores 0-100 for pricing/value/experience, 2-4 sections with charts
(type="bar" or "line", data=[{{label, value}}]), and 3-5 recommendations.

Competitors:
{competitors}
"""
