"""Normalized OCR output (architecture.md §0.13).

Every `OCRProvider` implementation normalizes to this schema regardless of
the vendor-specific response shape, so business logic and the AI provider
never need to know which OCR vendor produced it.
"""

from pydantic import BaseModel, Field


class ExtractedDocument(BaseModel):
    text: str
    page_count: int = Field(ge=0)
    # Vendor-reported average confidence for the extraction, 0-1. `None`
    # when the provider doesn't surface one.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
