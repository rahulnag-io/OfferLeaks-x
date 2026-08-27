"""Upload file validation (architecture.md §0.11: "strict MIME/type
validation, file size caps").

Sniffs the file's actual leading bytes rather than trusting the
client-supplied `Content-Type` header or filename extension -- either of
those can be forged trivially and this is the very first line of defense
before a file is scanned, stored, or ever reaches the OCR provider.
"""

from offerleaks.core.config import Settings

_MAGIC_BYTES: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


class FileValidationError(Exception):
    """Base class for all upload-validation failures. Routers map this to
    a 4xx, never a 5xx -- these are client mistakes, not server errors."""


class FileTooLargeError(FileValidationError):
    pass


class UnsupportedFileTypeError(FileValidationError):
    pass


def detect_mime_type(file_bytes: bytes) -> str | None:
    """Returns the sniffed MIME type, or `None` if it doesn't match any
    supported signature."""
    for mime_type, signature in _MAGIC_BYTES.items():
        if file_bytes.startswith(signature):
            return mime_type
    return None


def validate_upload(*, file_bytes: bytes, settings: Settings) -> str:
    """Validates size and sniffs the real MIME type.

    Returns the sniffed (trusted) MIME type on success -- callers should
    persist and act on this, not whatever the client claimed.
    """
    if len(file_bytes) == 0:
        raise UnsupportedFileTypeError("uploaded file is empty")
    if len(file_bytes) > settings.max_upload_size_bytes:
        raise FileTooLargeError(
            f"file exceeds the {settings.max_upload_size_bytes} byte limit"
        )

    mime_type = detect_mime_type(file_bytes)
    if mime_type is None or mime_type not in settings.allowed_upload_mime_type_set:
        raise UnsupportedFileTypeError("file type is not supported")

    return mime_type
