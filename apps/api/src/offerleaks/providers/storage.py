"""Object storage behind an interface (architecture.md §0.4).

S3-compatible (Cloudflare R2 at MVP, swappable to AWS S3 later via
config alone -- both speak the same S3 API, so `boto3` with a configured
`endpoint_url` covers both without a second client implementation).
Original uploaded offer letters live here, never in Postgres.
"""

import asyncio
from typing import Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from offerleaks.core.config import Settings
from offerleaks.providers.errors import PermanentProviderError, TransientProviderError


class StorageError(PermanentProviderError):
    """Storage operation failed in a way that isn't worth retrying inline
    (e.g. bad credentials, bucket missing). Transient network errors are
    raised as `StorageTransientError` instead."""


class StorageTransientError(TransientProviderError):
    pass


class StorageProvider(Protocol):
    """Business logic and workers depend on this, never on `boto3` (or any
    other vendor SDK) directly."""

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None: ...

    async def download(self, *, key: str) -> bytes: ...


class S3StorageProvider:
    """boto3-backed implementation, pointed at R2/S3 via `endpoint_url`."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key_id,
            aws_secret_access_key=settings.storage_secret_access_key,
            region_name=settings.storage_region,
            config=BotoConfig(signature_version="s3v4"),
        )

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        # boto3's S3 client is sync; storage calls run in a background
        # worker or a short-lived request path, so a thread hop here is
        # fine (see architecture.md §0.13's OCR provider for the same
        # sync-SDK-in-async-app pattern).
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to upload object {key!r}") from exc

    async def download(self, *, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            return response["Body"].read()  # type: ignore[no-any-return]
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to download object {key!r}") from exc
