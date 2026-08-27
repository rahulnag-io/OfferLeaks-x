"""Deterministic extraction of company-resolution inputs from an offer
letter's OCR'd text (M7: Company Signal & Reputation).

M7's roadmap describes resolution as running off "the sender email
domain" and "extracted company name already available from the existing
analysis pipeline" -- but this pipeline analyzes uploaded offer-letter
*documents*, not inbound email, and no prior version extracts a company
name. Rather than adding an AI call for this (M7 explicitly requires
"no new AI functionality"), this module is the smallest reasonable
deterministic stand-in: plain regex/heuristic extraction over the same
OCR text the rules engine already scans, run alongside it in the worker.

Both fields are best-effort and frequently `None` -- that's expected and
handled explicitly by `CompanyProfileService`/`company_normalization`,
never treated as an error.

**Recall note (audit finding):** many real offer letters (particularly
ones vague enough to be worth flagging in the first place -- see the
rules engine's own scam patterns) omit a proper email address entirely,
and don't use any of "on behalf of:"/"company name:"/a trailing legal
suffix for their company name either. The fallbacks below (a bare
website mention for the domain; a short, unlabeled letterhead-style
first line for the name) trade a small amount of precision for
meaningfully better recall on exactly that kind of document, rather than
silently resolving nothing. They're deliberately weighted *below* the
stronger, narrower signals above them.
"""

import re
from dataclasses import dataclass

from offerleaks.services.company_normalization import is_freemail_domain, normalize_domain

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})")

# A bare domain/URL mention (no "@", just "visit us at acme.com" or
# "www.acme.com") -- only ever consulted as a fallback when the document
# has no usable email address at all (see `_extract_sender_domain`).
_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)+\.[a-z]{2,})",
    re.IGNORECASE,
)

# Well-known third-party platforms/services that show up incidentally in
# offer letters (a Google Form link, a Zoom invite, a WhatsApp number)
# and must never be mistaken for the company's own domain, the same way
# freemail addresses are excluded from the email-based signal.
_THIRD_PARTY_PLATFORM_DOMAINS = frozenset(
    {
        "google.com",
        "docs.google.com",
        "drive.google.com",
        "forms.gle",
        "forms.office.com",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "zoom.us",
        "meet.google.com",
        "calendly.com",
        "youtube.com",
        "microsoft.com",
        "office.com",
        "dropbox.com",
        "wa.me",
        "whatsapp.com",
        "bit.ly",
        "tinyurl.com",
        "t.co",
    }
)

# Conservative letterhead/signature heuristics for a company display
# name, checked first (highest precision) -- a missed name here just
# falls through to the broader letterhead-line fallback below, or
# ultimately to the sender domain, before giving up entirely.
_NAME_LINE_PATTERNS = (
    re.compile(r"(?im)^\s*(?:on behalf of|from)\s*[:\-]?\s*(.+)$"),
    re.compile(r"(?im)^\s*company(?: name)?\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^\s*(.+?\b(?:Inc|Incorporated|Corp|Corporation|LLC|Ltd|Limited|Pvt|PLC|GmbH)\.?)\s*$"),
)
_MAX_EXTRACTED_NAME_LENGTH = 200

# Boilerplate document-header phrases that must never be mistaken for a
# company name by the broader first-line fallback below.
_GENERIC_HEADER_PHRASES = frozenset(
    {
        "offer letter",
        "internship offer",
        "internship offer letter",
        "employment offer",
        "employment offer letter",
        "job offer",
        "job offer letter",
        "offer of employment",
        "congratulations",
        "welcome aboard",
        "welcome to the team",
        "dear",
        "subject",
        "date",
        "re",
        "to whom it may concern",
    }
)


@dataclass(frozen=True, slots=True)
class ExtractedCompanySignals:
    sender_domain: str | None
    company_name: str | None


def _extract_sender_domain(text: str) -> str | None:
    """Picks the most likely "official" domain for the document: the
    most frequent non-freemail domain among email addresses found
    (weighted highest -- an actual address is the strongest signal),
    falling back to a bare website mention (e.g. "visit us at
    acme.com") only when there is no usable email address at all.
    Freemail domains and well-known third-party platforms are excluded
    from consideration entirely.
    """
    domains: dict[str, int] = {}
    for match in _EMAIL_PATTERN.finditer(text):
        candidate = normalize_domain(match.group(1))
        if candidate is None or is_freemail_domain(candidate):
            continue
        domains[candidate] = domains.get(candidate, 0) + 2

    if not domains:
        for match in _URL_PATTERN.finditer(text):
            candidate = normalize_domain(match.group(1))
            if candidate is None or is_freemail_domain(candidate):
                continue
            if candidate in _THIRD_PARTY_PLATFORM_DOMAINS:
                continue
            domains[candidate] = domains.get(candidate, 0) + 1

    if not domains:
        return None
    return max(domains.items(), key=lambda item: item[1])[0]


def _extract_company_name(text: str) -> str | None:
    # Only look at the first ~40 lines (letterhead/opening) and the last
    # ~15 (signature block) -- a company name mentioned deep in boilerplate
    # body text is far less reliably "the sender," and scanning the whole
    # document risks picking up an unrelated proper noun.
    lines = text.splitlines()
    window = lines[:40] + lines[-15:]
    candidate_text = "\n".join(window)

    for pattern in _NAME_LINE_PATTERNS:
        match = pattern.search(candidate_text)
        if match:
            name = match.group(1).strip()
            if name and len(name) <= _MAX_EXTRACTED_NAME_LENGTH:
                return name

    # Fallback: many real offer letters lead with a short, unlabeled
    # brand/company line -- no "on behalf of," no colon, just the name
    # by itself near the top -- rather than any of the explicit patterns
    # above. Conservative on purpose: only the first handful of
    # non-empty lines are considered, generic document-header phrases
    # are excluded, and the candidate must look like a short name (a
    # handful of capitalized words), not a sentence.
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    for candidate in non_empty_lines[:8]:
        if len(candidate) > 60:
            continue
        lowered = candidate.lower().rstrip(":!.,;")
        if any(
            lowered == phrase
            or lowered.startswith(phrase + " ")
            or lowered.startswith(phrase + ",")
            for phrase in _GENERIC_HEADER_PHRASES
        ):
            continue
        word_count = len(candidate.split())
        if word_count == 0 or word_count > 6:
            continue
        if not candidate[0].isupper() or candidate.islower():
            continue
        return candidate

    return None


def extract_company_signals(text: str) -> ExtractedCompanySignals:
    return ExtractedCompanySignals(
        sender_domain=_extract_sender_domain(text),
        company_name=_extract_company_name(text),
    )
