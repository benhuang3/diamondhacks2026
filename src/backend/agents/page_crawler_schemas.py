"""Pydantic models for structured output from the page-crawler agent.

These schemas are passed to the browser-use Cloud agent via
``schema``/``output_model_schema`` so the agent is constrained to
return well-shaped JSON describing a BFS walk across a storefront.
Length caps mirror ``competitor_schemas.py`` to keep downstream
prompts and DB rows bounded.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PageKind = Literal["home", "category", "product", "cart", "other"]


class InteractiveElement(BaseModel):
    """One interactive element observed on a visited page."""

    tag: str = Field(
        default="",
        max_length=16,
        description="HTML tag, e.g. 'button', 'a', 'input', 'img'",
    )
    selector: str = Field(
        default="",
        max_length=200,
        description="Best CSS selector for the element",
    )
    text: str = Field(
        default="",
        max_length=80,
        description="Visible label or alt text, <=80 chars",
    )


class PageVisit(BaseModel):
    """One page the crawler visited during the BFS walk."""

    url: str = Field(default="", max_length=2048, description="Absolute URL visited")
    title: str = Field(default="", max_length=200, description="Page title")
    kind: PageKind = Field(
        default="other",
        description="Rough role of the page in the storefront",
    )
    interactive_elements: list[InteractiveElement] = Field(
        default_factory=list,
        description="Up to 12 interactive elements observed on the page",
    )
    missing_alt_images: int = Field(
        default=0,
        description="Count of <img> elements missing an alt attribute",
    )
    low_contrast_count: int = Field(
        default=0,
        description="Rough count of low-contrast text/interactive elements",
    )


class CrawlSnapshot(BaseModel):
    """Structured output from the multi-page crawler agent."""

    pages: list[PageVisit] = Field(
        default_factory=list,
        description="Ordered list of pages visited (home first, cart last)",
    )
