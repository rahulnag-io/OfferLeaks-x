"""OCR behind an `OCRProvider` interface (architecture.md §0.13).

Google Document AI is the locked-in Version 3 provider. Business logic
and the worker call `OCRProvider.extract()`, never the Document AI SDK
directly, so adding a second OCR provider later is a config addition,
not a refactor.
"""

import asyncio
from typing import Protocol

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import documentai

from offerleaks.core.config import Settings
from offerleaks.providers.errors import PermanentProviderError, TransientProviderError
from offerleaks.schemas.ocr import ExtractedDocument


class OCRPermanentError(PermanentProviderError):
    pass


class OCRTransientError(TransientProviderError):
    pass


class OCRProvider(Protocol):
    async def extract(self, *, file_bytes: bytes, mime_type: str) -> ExtractedDocument: ...


class GoogleDocumentAIProvider:
    """Runs the (synchronous) Document AI client in a worker thread --
    the SDK has no native asyncio client, and this call always happens
    inside the background worker anyway (§0.13: "never inline in the
    request/response cycle")."""

    def __init__(self, settings: Settings) -> None:
        if not settings.google_document_ai_project_id or not (
            settings.google_document_ai_processor_id
        ):
            raise OCRPermanentError("Google Document AI is not configured")

        self._processor_name = (
            f"projects/{settings.google_document_ai_project_id}"
            f"/locations/{settings.google_document_ai_location}"
            f"/processors/{settings.google_document_ai_processor_id}"
        )
        api_endpoint = f"{settings.google_document_ai_location}-documentai.googleapis.com"
        self._client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": api_endpoint}
        )

    def _process_sync(self, file_bytes: bytes, mime_type: str) -> documentai.Document:
        request = documentai.ProcessRequest(
            name=self._processor_name,
            raw_document=documentai.RawDocument(content=file_bytes, mime_type=mime_type),
        )
        result = self._client.process_document(request=request)
        return result.document

    async def extract(self, *, file_bytes: bytes, mime_type: str) -> ExtractedDocument:
        try:
            document = await asyncio.to_thread(self._process_sync, file_bytes, mime_type)
        except RetryError as exc:
            raise OCRTransientError("Document AI request timed out") from exc
        except GoogleAPICallError as exc:
            # 429/503-class errors are retryable; anything else (bad
            # request, permission denied, unsupported document) is not.
            if exc.code is not None and exc.code in (429, 500, 502, 503, 504):
                raise OCRTransientError(str(exc)) from exc
            raise OCRPermanentError(str(exc)) from exc

        confidence: float | None = None
        scores = [
            block.layout.confidence
            for page in document.pages
            for block in page.blocks
            if block.layout is not None
        ]
        if scores:
            confidence = sum(scores) / len(scores)

        return ExtractedDocument(
            text=document.text,
            page_count=len(document.pages),
            confidence=confidence,
        )
