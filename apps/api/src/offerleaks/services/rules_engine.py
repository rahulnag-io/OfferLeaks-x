"""M6: Trust Verdict + Monetization Foundation -- the rules engine.

Three independent, deterministic responsibilities, deliberately kept out
of the AI call (Revised_ARCHITECTURE.md M6: "runs before/alongside the AI
call, not instead of it"):

1. `match` -- scan the OCR'd document text against the active
   `ScamPattern` library (case-insensitive keyword matching, see
   `models/scam_pattern.py` for why this is intentionally simple).
2. `evidence_coverage` -- score how much of a verdict's AI-produced
   `red_flags` are backed by a literal `evidence_quote`.
3. `recommended_actions_for` -- a small, explicitly rule-based mapping
   from risk level to 2-4 next-step strings. No model call, no
   fabricated "personalized" advice -- the roadmap calls this out by
   name as the cheap, high-trust feature to build first.

None of this owns persistence -- `worker.py` calls this service, then
`AnalysisRepository.create_verdict` writes the result. Keeping it a pure
service (no DB writes) makes it directly unit-testable against a labeled
set of known scam letters, per M6's own testing requirement.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.repositories.scam_pattern_repository import ScamPatternRepository
from offerleaks.schemas.ai import RedFlag, RedFlagSeverity
from offerleaks.schemas.patterns import MatchedPattern

# Ordered worst-to-first so a single high-severity match always wins the
# "how urgent is this" framing over a pile of low-severity ones.
_SEVERITY_RANK: dict[RedFlagSeverity, int] = {
    RedFlagSeverity.HIGH: 2,
    RedFlagSeverity.MEDIUM: 1,
    RedFlagSeverity.LOW: 0,
}

_BASE_ACTIONS: tuple[str, ...] = (
    "Verify the company's official domain and contact details independently "
    "-- don't reply using the contact info in this document.",
)
_HIGH_RISK_ACTIONS: tuple[str, ...] = (
    "Do not send money, banking details, or ID documents in response to this offer.",
    "Contact the company directly through a phone number or website you find "
    "yourself, not one provided in this document.",
)
_MEDIUM_RISK_ACTIONS: tuple[str, ...] = (
    "Ask the company for a signed offer letter on official letterhead before "
    "taking any action.",
)
_LOW_RISK_ACTIONS: tuple[str, ...] = (
    "This looks reasonable, but it's still worth confirming the role and "
    "salary details directly with HR before accepting.",
)
_MAX_RECOMMENDED_ACTIONS = 4


@dataclass(frozen=True, slots=True)
class RulesEngineResult:
    matched_patterns: list[MatchedPattern]
    pattern_red_flags: list[RedFlag]


class RulesEngine:
    def __init__(self, db: AsyncSession) -> None:
        self._patterns = ScamPatternRepository(db)

    async def match(self, *, text: str) -> RulesEngineResult:
        """Matches `text` (the OCR'd document) against every active
        `ScamPattern`. Case-insensitive substring matching, first
        matching keyword only (per pattern) is kept as the evidence
        quote's source context -- a pattern either matches or it
        doesn't, there's no partial-credit scoring here.
        """
        active_patterns = await self._patterns.list_active()
        haystack = text.lower()

        matches: list[MatchedPattern] = []
        red_flags: list[RedFlag] = []
        for pattern in active_patterns:
            hit_keyword = next(
                (kw for kw in pattern.keywords if kw.lower() in haystack), None
            )
            if hit_keyword is None:
                continue

            matches.append(
                MatchedPattern(
                    pattern_key=pattern.key,
                    title=pattern.title,
                    severity=RedFlagSeverity(pattern.severity.value),
                )
            )
            red_flags.append(
                RedFlag(
                    title=pattern.title,
                    description=pattern.description,
                    severity=RedFlagSeverity(pattern.severity.value),
                    evidence_quote=_extract_context(haystack, text, hit_keyword),
                )
            )

        return RulesEngineResult(matched_patterns=matches, pattern_red_flags=red_flags)

    @staticmethod
    def evidence_coverage(red_flags: list[RedFlag]) -> float:
        """Fraction (0.0-1.0) of `red_flags` that carry a non-empty
        `evidence_quote`. `0.0` for an empty flag list -- "no flags"
        isn't the same claim as "no evidence for the flags we found," so
        this deliberately doesn't default to `1.0` on an empty list.
        """
        if not red_flags:
            return 0.0
        with_evidence = sum(1 for flag in red_flags if flag.evidence_quote)
        return round(with_evidence / len(red_flags), 4)

    @staticmethod
    def recommended_actions_for(
        *, risk_score: int, red_flags: list[RedFlag]
    ) -> list[str]:
        """Rule-based (not AI-generated) next steps, 2-4 short strings.

        Driven by `risk_score` bands plus the worst flag severity present
        -- not the AI's free-form reasoning text, so this can never
        contradict or duplicate the model's own prose, and stays cheap
        and auditable (a fixed, reviewable string catalog, not a
        generative call).
        """
        worst_severity = max(
            (flag.severity for flag in red_flags), key=lambda s: _SEVERITY_RANK[s], default=None
        )

        actions: list[str] = list(_BASE_ACTIONS)
        if risk_score >= 70 or worst_severity == RedFlagSeverity.HIGH:
            actions.extend(_HIGH_RISK_ACTIONS)
        elif risk_score >= 35 or worst_severity == RedFlagSeverity.MEDIUM:
            actions.extend(_MEDIUM_RISK_ACTIONS)
        else:
            actions.extend(_LOW_RISK_ACTIONS)

        return actions[:_MAX_RECOMMENDED_ACTIONS]


def _extract_context(haystack: str, original_text: str, keyword: str) -> str:
    """Returns up to ~120 characters of `original_text` centered on the
    first case-insensitive occurrence of `keyword`, as the pattern-match
    flag's evidence quote. Falls back to the keyword itself (should be
    unreachable given the caller only calls this after confirming a hit,
    but stays a safe default rather than raising).
    """
    idx = haystack.find(keyword.lower())
    if idx == -1:
        return keyword

    window = 60
    start = max(0, idx - window)
    end = min(len(original_text), idx + len(keyword) + window)
    snippet = original_text[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(original_text) else ""
    return f"{prefix}{snippet}{suffix}"[:500]
