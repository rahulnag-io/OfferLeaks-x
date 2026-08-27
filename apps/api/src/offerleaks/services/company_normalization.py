"""Company/domain identity normalization (M7: Company Signal & Reputation).

The single place that decides what "the same company" means. Every
caller that needs to look up, create, or cache a `Company` row goes
through `resolve_identity_key` here -- never normalizes a domain or name
itself -- so "equivalent representations do not create duplicate company
records or duplicate cache entries" (M7 requirement) holds structurally
rather than by convention.

Deliberately simple, deterministic string normalization -- no fuzzy
matching, no external entity-resolution service. That's consistent with
the "smallest reasonable deterministic resolution strategy" the roadmap
asks for, and with M7's broader "no fragile infrastructure" instruction.
"""

import re
import unicodedata

# Legal-entity suffixes stripped from a company name before it's used as
# a fallback identity key -- "Acme Corp", "Acme Corporation", and "Acme
# Inc." should all resolve to the same company when no domain is
# available. Deliberately conservative/English-centric for v1; expanding
# this list is additive and safe (it can only ever *merge* previously-
# separate keys, never split an existing one retroactively).
_LEGAL_SUFFIXES = (
    "incorporated",
    "corporation",
    "company",
    "limited",
    "llc",
    "inc",
    "corp",
    "ltd",
    "co",
    "pvt",
    "plc",
    "gmbh",
)
_SUFFIX_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\.?\s*$",
    re.IGNORECASE,
)
_NON_ALNUM_WHITESPACE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")

# A free/consumer email provider is never itself "the company's domain"
# -- resolving a company identity to gmail.com would silently merge
# every scammer (and every legitimate small business) that happens to
# use free email into one giant, meaningless "company." Reused from the
# same reasoning as M6's `free_email_domain_official` scam pattern.
FREEMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "aol.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "mail.com",
        "gmx.com",
        "live.com",
        "yandex.com",
        "rediffmail.com",
        "zoho.com",
    }
)


def normalize_domain(domain: str | None) -> str | None:
    """Lowercases, strips whitespace/scheme/path/port/leading `www.`, and
    validates a minimally-sane shape. Returns `None` for anything that
    doesn't normalize into a plausible domain (malformed input is treated
    as "no domain," never as an error the caller has to handle
    separately -- M7 §14's "malformed or unusual domains" edge case)."""
    if not domain:
        return None

    candidate = domain.strip().lower()
    candidate = re.sub(r"^[a-z][a-z0-9+.-]*://", "", candidate)  # strip a scheme, if present
    candidate = candidate.split("/", 1)[0]  # strip any path
    candidate = candidate.split("@", 1)[-1]  # tolerate an email being passed in by mistake
    candidate = candidate.split(":", 1)[0]  # strip a port
    if candidate.startswith("www."):
        candidate = candidate[len("www.") :]

    # Minimal sanity check: at least one dot, only label-safe characters,
    # no empty labels (e.g. "a..com" or a bare "com").
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9-]{1,63})+", candidate):
        return None

    return candidate


def is_freemail_domain(domain: str | None) -> bool:
    normalized = normalize_domain(domain)
    return normalized is not None and normalized in FREEMAIL_DOMAINS


def normalize_company_name(name: str | None) -> str | None:
    """Lowercases, strips accents/punctuation, collapses whitespace, and
    drops a trailing legal-entity suffix, so "Acme Corp.", "ACME
    CORPORATION", and "acme corp" all normalize identically. Returns
    `None` for anything that normalizes to empty (e.g. the name was
    nothing but punctuation)."""
    if not name:
        return None

    candidate = unicodedata.normalize("NFKD", name)
    candidate = "".join(ch for ch in candidate if not unicodedata.combining(ch))
    candidate = candidate.lower()
    candidate = _NON_ALNUM_WHITESPACE.sub(" ", candidate)
    candidate = _WHITESPACE.sub(" ", candidate).strip()
    if not candidate:
        return None

    stripped = _SUFFIX_PATTERN.sub("", candidate).strip()
    # Only drop the suffix if something real is left -- a company
    # literally just named "Ltd" shouldn't normalize to an empty key.
    if stripped:
        candidate = stripped

    return candidate or None


def resolve_identity_key(*, domain: str | None, company_name: str | None) -> str | None:
    """The single normalized identity key `CompanyRepository` looks
    up/creates by. A domain is always preferred over a name when both
    are available -- it's the more reliable, less ambiguous signal (two
    different real companies can plausibly share a display name; they
    can't share a domain). Returns `None` when neither input normalizes
    to anything usable, meaning: nothing to resolve at all (M7's honest
    "unable to verify" case, handled by the caller, not here)."""
    normalized_domain = normalize_domain(domain)
    if normalized_domain is not None:
        return f"domain:{normalized_domain}"

    normalized_name = normalize_company_name(company_name)
    if normalized_name is not None:
        return f"name:{normalized_name}"

    return None
