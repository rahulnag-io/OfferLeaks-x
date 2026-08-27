"""Fake provider implementations used across the analysis test suite.

These stand in for the real `StorageProvider`/`OCRProvider`/`AIProvider`/
`MalwareScanProvider` implementations, which talk to Google Document AI,
Anthropic, ClamAV, and S3/R2 respectively -- none of which are reachable
or safe to hit from an automated test run. This mirrors exactly why the
providers are behind interfaces in the first place (architecture.md
§0.6/§0.13): the business logic and worker being tested here never know
or care that they're talking to a fake.
"""

from dataclasses import dataclass, field

from offerleaks.providers.ai import AIPermanentError, AITransientError
from offerleaks.providers.malware_scan import ScanResult
from offerleaks.providers.ocr import OCRPermanentError, OCRTransientError
from offerleaks.providers.storage import StorageError
from offerleaks.schemas.ai import RedFlag, RedFlagSeverity, VerdictSchema
from offerleaks.schemas.ocr import ExtractedDocument


class FakeStorageProvider:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def download(self, *, key: str) -> bytes:
        # Mirrors S3StorageProvider: a missing object is a typed
        # StorageError, not a raw KeyError -- callers only ever need to
        # handle the provider-interface error type.
        try:
            return self.objects[key]
        except KeyError as exc:
            raise StorageError(f"no such object: {key!r}") from exc


@dataclass
class FakeMalwareScanProvider:
    result: ScanResult = field(default_factory=lambda: ScanResult(is_clean=True))
    raise_unavailable: bool = False

    async def scan(self, *, file_bytes: bytes) -> ScanResult:
        if self.raise_unavailable:
            from offerleaks.providers.malware_scan import ScanUnavailableError

            raise ScanUnavailableError("scanner unreachable")
        return self.result


DEFAULT_EXTRACTED_TEXT = "Dear Alice, we are pleased to offer you the position of Engineer..."


@dataclass
class FakeOCRProvider:
    document: ExtractedDocument | None = None
    permanent_error: bool = False
    transient_error_count: int = 0

    def __post_init__(self) -> None:
        if self.document is None:
            self.document = ExtractedDocument(text=DEFAULT_EXTRACTED_TEXT, page_count=1)
        self._calls = 0

    async def extract(self, *, file_bytes: bytes, mime_type: str) -> ExtractedDocument:
        self._calls += 1
        if self.permanent_error:
            raise OCRPermanentError("corrupt document")
        if self._calls <= self.transient_error_count:
            raise OCRTransientError("timeout")
        assert self.document is not None
        return self.document


DEFAULT_VERDICT = VerdictSchema(
    risk_score=15,
    red_flags=[
        RedFlag(
            title="Minor formatting inconsistency",
            description="Signature block font differs from the rest of the letter.",
            severity=RedFlagSeverity.LOW,
        )
    ],
    reasoning="The letter's structure, tone, and details are consistent with a legitimate offer.",
    confidence=0.82,
)


@dataclass
class FakeAIProvider:
    verdict: VerdictSchema = field(default_factory=lambda: DEFAULT_VERDICT)
    always_fails: bool = False
    transient: bool = True

    async def analyze_offer_letter(self, *, text: str, prompt_version: str) -> VerdictSchema:
        if self.always_fails:
            if self.transient:
                raise AITransientError("model overloaded")
            raise AIPermanentError("model refused to call the tool")
        return self.verdict
