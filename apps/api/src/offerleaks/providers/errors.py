"""Typed errors for provider implementations.

Shared across storage/OCR/AI/malware-scan providers so callers (the
analysis worker) can distinguish "retry me" from "give up and surface a
typed failure" without knowing which vendor raised it (§0.13: "Retries
with backoff on transient failures, typed error surfaced -- not silently
swallowed -- on permanent failure").
"""


class ProviderError(Exception):
    """Base class for all provider failures."""


class TransientProviderError(ProviderError):
    """A retryable failure: timeout, rate limit, transient network error."""


class PermanentProviderError(ProviderError):
    """A non-retryable failure: malformed input, auth failure, unsupported
    document, or a provider response that fails schema validation after
    the vendor's own structured-output/tool-calling mode was used."""
