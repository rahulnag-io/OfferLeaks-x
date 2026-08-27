"""Structured AI-verdict contract (architecture.md §0.6).

Every `AIProvider` implementation must return this shape -- using the
vendor's native structured-output/tool-calling mode, never regex-parsing
free text. If a provider can't produce this shape, that's a typed
`AIProviderError`, not a silently-wrong verdict.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class RedFlagSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RedFlag(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(max_length=1000)
    severity: RedFlagSeverity
    # M6 "Evidence Highlighting": a short, verbatim quote copied from the
    # analyzed document that backs this flag. Optional -- not every flag
    # (e.g. "no registered business address found anywhere") can be
    # pinned to a literal span, and a model forced to fabricate one would
    # be worse than an honest `None`. `evidence_coverage` on the verdict
    # (computed server-side, see `services/rules_engine.py`) is the
    # fraction of a verdict's flags that *do* have one -- that's the
    # signal surfaced to the user, not a per-flag requirement.
    evidence_quote: str | None = Field(default=None, max_length=500)


class VerdictSchema(BaseModel):
    """The AI's structured output for one offer letter."""

    risk_score: int = Field(ge=0, le=100)
    red_flags: list[RedFlag]
    reasoning: str = Field(max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
