"""Pydantic models for structured output from the competitor browser agent.

These schemas are passed to `browser_use.Agent` via `output_model_schema`
so the agent is constrained to return well-shaped JSON. Length caps are
enforced at the model layer to keep downstream Claude prompts bounded.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CompetitorSnapshot(BaseModel):
    """Front-page snapshot of a competitor storefront."""

    title: str = Field(default="", max_length=200, description="Page title")
    featured_product: str = Field(
        default="",
        max_length=160,
        description=(
            "Short name of the dominant product showcased on the front "
            "page (e.g. 'Blue Leather Bifold Wallet'). Leave empty if "
            "the front page is generic and no single product is featured."
        ),
    )
    featured_price: Optional[float] = Field(
        default=None,
        description="Representative price on front page, USD, or null",
    )
    promos: list[str] = Field(
        default_factory=list,
        description="Promo codes / sale banners, each <=120 chars, <=5 items",
    )
    shipping_note: str = Field(
        default="",
        max_length=200,
        description="Shipping policy text, e.g. 'Free shipping over $35'",
    )
    notes: str = Field(
        default="",
        max_length=500,
        description="Other observations, <=500 chars",
    )
