"""Unit tests for `offerleaks.services.file_validation`.

No DB/Redis/network involved -- pure function tests over byte strings, so
these run instantly and don't need the `_clean_state`/real-infra fixtures
the endpoint tests use.
"""

import pytest

from offerleaks.core.config import Settings
from offerleaks.services.file_validation import (
    FileTooLargeError,
    UnsupportedFileTypeError,
    detect_mime_type,
    validate_upload,
)

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_detect_mime_type_recognizes_pdf() -> None:
    assert detect_mime_type(PDF_BYTES) == "application/pdf"


def test_detect_mime_type_recognizes_jpeg() -> None:
    assert detect_mime_type(JPEG_BYTES) == "image/jpeg"


def test_detect_mime_type_recognizes_png() -> None:
    assert detect_mime_type(PNG_BYTES) == "image/png"


def test_detect_mime_type_rejects_unknown_signature() -> None:
    assert detect_mime_type(b"not a real file") is None


def test_detect_mime_type_ignores_claimed_content_type_and_looks_at_bytes() -> None:
    # A text file renamed to look like a PDF via its (irrelevant here)
    # filename is still sniffed by its actual leading bytes.
    assert detect_mime_type(b"just some text, not a pdf") is None


def test_validate_upload_accepts_a_well_formed_pdf(settings: Settings) -> None:
    mime_type = validate_upload(file_bytes=PDF_BYTES, settings=settings)
    assert mime_type == "application/pdf"


def test_validate_upload_rejects_empty_file(settings: Settings) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload(file_bytes=b"", settings=settings)


def test_validate_upload_rejects_disallowed_type(settings: Settings) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload(file_bytes=b"GIF89a" + b"\x00" * 20, settings=settings)


def test_validate_upload_rejects_oversized_file(settings: Settings) -> None:
    settings.max_upload_size_bytes = 10
    with pytest.raises(FileTooLargeError):
        validate_upload(file_bytes=PDF_BYTES, settings=settings)


def test_validate_upload_rejects_type_not_in_allowlist(settings: Settings) -> None:
    settings.allowed_upload_mime_types = "image/png"
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload(file_bytes=PDF_BYTES, settings=settings)
