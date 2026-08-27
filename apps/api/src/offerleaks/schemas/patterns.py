"""Rules-engine match result shape (M6: Scam Pattern Library).

Deliberately separate from `schemas/ai.py`: `VerdictSchema` is the *AI
provider's* contract (§0.6 -- native tool-calling, one shape every
`AIProvider` must return). A `MatchedPattern` is never produced by the
AI call; it's the deterministic output of `RulesEngine` matching the
OCR'd document text against `ScamPattern` rows, so it gets its own
schema rather than overloading the provider contract.
"""

from pydantic import BaseModel

from offerleaks.schemas.ai import RedFlagSeverity


class MatchedPattern(BaseModel):
    """One `ScamPattern` that matched the analyzed document."""

    pattern_key: str
    title: str
    severity: RedFlagSeverity
