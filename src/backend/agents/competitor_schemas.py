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


class OtherProductPrice(BaseModel):
    """Price observed for a non-primary shared product during navigation."""

    product: str = Field(default="", max_length=160)
    price: Optional[float] = None


class CheckoutSnapshot(BaseModel):
    """Deeper checkout-walk snapshot of a competitor storefront.

    Captures the real price breakdown (subtotal, shipping, tax, fees,
    total) after adding a product to cart and reaching the checkout
    preview page. Do NOT place orders or enter payment info.
    """

    title: str = Field(default="", max_length=200)
    featured_product: str = Field(default="", max_length=160)
    product_url: str = Field(default="", max_length=2048)
    pages_visited: list[str] = Field(default_factory=list)
    price: Optional[float] = None
    shipping: Optional[float] = None
    tax: Optional[float] = None
    fees: Optional[float] = None
    discount_code: Optional[str] = Field(default=None, max_length=80)
    discount_amount: Optional[float] = None
    checkout_total: Optional[float] = None
    promos: list[str] = Field(default_factory=list)
    shipping_note: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=500)
    reached_checkout: bool = False
    # Prices for OTHER shared product categories spotted in passing while
    # browsing (catalog page, nav, related products). No extra clicks —
    # empty list is fine when the agent can't find them.
    other_product_prices: list[OtherProductPrice] = Field(default_factory=list)


class DiscoveredCompetitor(BaseModel):
    """One competitor storefront proposed by the discovery agent."""

    name: str = Field(default="", max_length=160)
    url: str = Field(default="", max_length=2048)
    rationale: str = Field(default="", max_length=500)


class CompetitorList(BaseModel):
    """Structured output from the discovery agent."""

    competitors: list[DiscoveredCompetitor] = Field(default_factory=list)


class SharedProduct(BaseModel):
    """One product type that the target store + competitors likely share."""

    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=240)
    # 0-100: how confident Claude is that all stores carry this.
    match_likelihood: int = Field(default=50)


class SharedProductList(BaseModel):
    """Top-3 shared product types across target + competitors."""

    products: list[SharedProduct] = Field(default_factory=list)
