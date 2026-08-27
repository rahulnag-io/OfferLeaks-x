"""Deterministic duplicate-report detection (M8: Structured Reporting).

Centralized here, not duplicated in the router/repository/frontend (M8
§8: "duplicate detection is deterministic and centralized"). No AI/
embeddings/semantic search -- `difflib.SequenceMatcher` on a normalized
form of the description is the smallest reasonable deterministic
strategy that can tell "materially the same complaint" apart from
"different complaint about the same company," which is exactly what the
roadmap asks for (M8 §"Duplicate-report detection").

`normalize_report_text` deliberately reuses the same shape of
normalization as `services/company_normalization.py` (lowercase, strip,
collapse whitespace) rather than inventing a second text-normalization
convention.
"""

import re
from difflib import SequenceMatcher

# Below this similarity ratio, two descriptions are treated as
# meaningfully different complaints about the same company, not a
# duplicate -- picked conservatively (fairly high bar) so legitimate,
# distinct reports about the same company are never silently collapsed
# together (M8 §7: "avoid blindly treating every report about the same
# company as a duplicate").
DEFAULT_SIMILARITY_THRESHOLD = 0.72

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")


def normalize_report_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Pure function,
    no I/O -- safe to call at submission time and to persist the result
    (`Report.description_normalized`) so later duplicate-window queries
    never re-normalize on every read.
    """
    lowered = text.strip().lower()
    no_punctuation = _PUNCTUATION_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", no_punctuation).strip()


def similarity_ratio(a: str, b: str) -> float:
    """Deterministic [0.0, 1.0] similarity between two already-normalized
    strings. `SequenceMatcher` is stdlib, deterministic, and needs no
    external service/model -- exactly what M8 §"AI changes" requires
    ("avoid AI calls," "avoid... embedding infrastructure").
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def is_duplicate_description(
    candidate_normalized: str,
    existing_normalized: str,
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    return similarity_ratio(candidate_normalized, existing_normalized) >= threshold
