from __future__ import annotations

import hashlib
import os
import shutil
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .storage import WorkflowError, write_json


MAX_IMAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class UploadedImage:
    url: str
    pathname: str
    content_type: str


class ImageUploader(Protocol):
    @property
    def destination_id(self) -> str: ...

    def upload(
        self, source: Path, *, pathname: str, content_type: str
    ) -> UploadedImage: ...

    def accepts_public_url(self, url: str) -> bool: ...


class BlobUploadError(WorkflowError):
    def __init__(self, code: str, message: str, *, needs_configuration: bool) -> None:
        super().__init__(message)
        self.code = code
        self.needs_configuration = needs_configuration


class FakePublicBlobUploader:
    """Validation-only public Blob boundary with deterministic URLs."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def destination_id(self) -> str:
        return self.directory.resolve().as_uri()

    def upload(
        self, source: Path, *, pathname: str, content_type: str
    ) -> UploadedImage:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        suffix = Path(pathname).suffix
        object_path = self.directory / "objects" / f"{digest}{suffix}"
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if object_path.exists() and object_path.read_bytes() != source.read_bytes():
            raise WorkflowError("Fake Blob pathname was reused with other bytes")
        if not object_path.exists():
            shutil.copyfile(source, object_path)
        url = "https://fake-public-blob.example/" + urllib.parse.quote(
            pathname, safe="/"
        )
        write_json(
            self.directory / "metadata" / f"{digest}.json",
            {
                "url": url,
                "pathname": pathname,
                "content_type": content_type,
                "sha256": digest,
            },
        )
        return UploadedImage(url=url, pathname=pathname, content_type=content_type)

    def accepts_public_url(self, url: str) -> bool:
        return url.startswith("https://fake-public-blob.example/")


class VercelPublicBlobUploader:
    """Upload local files to a Public Vercel Blob store via the official SDK."""

    def __init__(
        self,
        token_env: str = "BLOB_READ_WRITE_TOKEN",
        store_id_env: str = "BLOB_STORE_ID",
    ) -> None:
        self.token_env = token_env
        self.store_id_env = store_id_env

    @property
    def destination_id(self) -> str:
        return f"vercel-blob:public:{_runtime_store_id(self.store_id_env)}"

    def upload(
        self, source: Path, *, pathname: str, content_type: str
    ) -> UploadedImage:
        token = _runtime_secret(self.token_env)
        try:
            from vercel.blob import BlobClient
        except ImportError as error:
            raise BlobUploadError(
                "vercel_blob_sdk_missing",
                "Install the official Vercel Python SDK with: pip install vercel==0.3.4",
                needs_configuration=True,
            ) from error
        try:
            result = BlobClient(token=token).upload_file(
                source,
                pathname,
                access="public",
                content_type=content_type,
                overwrite=True,
            )
        except Exception as error:
            raise BlobUploadError(
                "vercel_blob_upload_failed",
                f"Vercel Blob upload failed: {error}",
                needs_configuration=False,
            ) from error
        url = getattr(result, "url", None)
        returned_pathname = getattr(result, "pathname", None)
        returned_content_type = getattr(result, "content_type", None)
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or ".public.blob.vercel-storage.com/" not in url
            or not isinstance(returned_pathname, str)
        ):
            raise BlobUploadError(
                "vercel_blob_response_invalid",
                "Vercel Blob did not return a valid Public Blob URL",
                needs_configuration=False,
            )
        return UploadedImage(
            url=url,
            pathname=returned_pathname,
            content_type=(
                returned_content_type
                if isinstance(returned_content_type, str)
                else content_type
            ),
        )

    def accepts_public_url(self, url: str) -> bool:
        return (
            url.startswith("https://")
            and ".public.blob.vercel-storage.com/" in url
        )


def image_format(content: bytes) -> tuple[str, str]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise BlobUploadError(
        "publication_image_type_unsupported",
        "Publication images must be JPEG, PNG, WebP, or GIF",
        needs_configuration=False,
    )


def validate_image_bytes(content: bytes) -> tuple[str, str]:
    if len(content) > MAX_IMAGE_BYTES:
        raise BlobUploadError(
            "publication_image_too_large",
            "Publication images must not exceed 10 MB",
            needs_configuration=False,
        )
    return image_format(content)


def _runtime_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise BlobUploadError(
            "blob_token_missing",
            f"Runtime secret {name} is missing",
            needs_configuration=True,
        )
    if (
        value != value.strip()
        or not value.isascii()
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
        or value[0] in "\"'"
        or value[-1] in "\"'"
    ):
        raise BlobUploadError(
            "blob_token_invalid_format",
            f"Runtime secret {name} must be unquoted printable ASCII",
            needs_configuration=True,
        )
    return value


def _runtime_store_id(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.startswith("store_") or not value.removeprefix("store_").isalnum():
        raise BlobUploadError(
            "blob_store_id_invalid",
            f"Runtime value {name} must use the store_<id> format",
            needs_configuration=True,
        )
    return value
