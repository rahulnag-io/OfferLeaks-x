"""Wires `Settings` to concrete provider implementations.

The single place that decides *which* `StorageProvider`/`OCRProvider`/
`AIProvider`/`MalwareScanProvider` a given config produces. FastAPI
dependencies and the RQ worker both call these instead of constructing
vendor clients themselves, so swapping a provider is a change here, not a
change at every call site.
"""

from functools import lru_cache

from offerleaks.core.config import Settings, get_settings
from offerleaks.providers.ai import AIProvider, AnthropicProvider
from offerleaks.providers.domain_age import DomainAgeProvider, RDAPDomainAgeProvider
from offerleaks.providers.malware_scan import (
    CloudmersiveMalwareScanProvider,
    MalwareScanProvider,
    NullMalwareScanProvider,
)
from offerleaks.providers.ocr import GoogleDocumentAIProvider, OCRProvider
from offerleaks.providers.payment import PaymentProvider, RazorpayProvider
from offerleaks.providers.storage import S3StorageProvider, StorageProvider
from offerleaks.providers.website_reachability import (
    HttpxWebsiteReachabilityProvider,
    WebsiteReachabilityProvider,
)


@lru_cache
def get_storage_provider() -> StorageProvider:
    return S3StorageProvider(get_settings())


@lru_cache
def get_ocr_provider() -> OCRProvider:
    return GoogleDocumentAIProvider(get_settings())


@lru_cache
def get_ai_provider() -> AIProvider:
    return AnthropicProvider(get_settings())


@lru_cache
def get_malware_scan_provider() -> MalwareScanProvider:
    settings: Settings = get_settings()
    if not settings.malware_scan_enabled:
        return NullMalwareScanProvider()
    return CloudmersiveMalwareScanProvider(settings)


@lru_cache
def get_payment_provider() -> PaymentProvider:
    return RazorpayProvider(get_settings())


@lru_cache
def get_domain_age_provider() -> DomainAgeProvider:
    return RDAPDomainAgeProvider(get_settings())


@lru_cache
def get_website_reachability_provider() -> WebsiteReachabilityProvider:
    return HttpxWebsiteReachabilityProvider(get_settings())
