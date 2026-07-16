from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .fake_blog import BlogAdapterError
from .rewrite import RewriteArtifact
from .schema_validation import SchemaValidationError, validate_record
from .storage import WorkflowError, write_immutable_bytes
from .submission import SCHEMA_VERSION


class DraftBlogAdapter(Protocol):
    """The complete external capability surface available to delivery."""

    def map_target(self, source_id: str) -> str:
        """Resolve one opaque publication target."""
        ...

    def upload_image(self, expected_sha256: str, content: bytes) -> str:
        """Upload one content-addressed image and return its stable asset ID."""
        ...

    def create_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        """Create or recover one idempotent draft; never publish it."""
        ...


def deliver_canonical_draft(
    task_directory: Path,
    task_id: str,
    artifact: RewriteArtifact,
    blog: DraftBlogAdapter,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    uploaded_images: list[dict[str, object]] = []
    for occurrence, relative_path in enumerate(artifact.images, start=1):
        asset_path = task_directory / relative_path
        sha256 = asset_path.name
        try:
            content = asset_path.read_bytes()
        except OSError as error:
            raise WorkflowError(f"Cannot read delivery image: {asset_path}") from error
        asset_id = blog.upload_image(sha256, content)
        uploaded_images.append(
            {
                "occurrence": occurrence,
                "asset_id": asset_id,
                "sha256": sha256,
            }
        )

    request: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": 1,
        "operation": "create_draft",
        "idempotency_key": task_id,
        "target": {
            "source_id": artifact.target_id,
            "external_id": blog.map_target(artifact.target_id),
        },
        "title": artifact.title,
        "body_markdown": artifact.content,
        "images": uploaded_images,
        "adapter": "fake",
    }
    validate_record("delivery-request", request)
    request_bytes = _json_bytes(request)
    write_immutable_bytes(task_directory / "delivery" / "request.json", request_bytes)
    attempt_directory = task_directory / "delivery" / "attempts" / run_id
    write_immutable_bytes(attempt_directory / "request.json", request_bytes)
    try:
        raw_response = blog.create_draft(request)
    except BlogAdapterError as error:
        _write_attempt_error(
            attempt_directory,
            task_id,
            run_id,
            error,
            phase="create_draft",
            response_received=False,
        )
        raise
    raw_response_bytes = _json_bytes(raw_response)
    write_immutable_bytes(
        attempt_directory / "response-raw.json", raw_response_bytes
    )
    if raw_response.get("state") == "rejected":
        rejected_error = BlogAdapterError(
            "rejected_response",
            "draft_rejected",
            "Blog service explicitly rejected the draft",
        )
        _write_attempt_error(
            attempt_directory,
            task_id,
            run_id,
            rejected_error,
            phase="validate_response",
            response_received=True,
        )
        raise rejected_error
    try:
        validate_record("fake-blog-response", raw_response)
        preview = raw_response.get("preview")
        if not isinstance(preview, str) or not preview.startswith("https://"):
            raise SchemaValidationError("fake-blog-response.preview must use https")
    except SchemaValidationError as error:
        adapter_error = BlogAdapterError(
            "invalid_response",
            "blog_response_invalid",
            str(error),
        )
        _write_attempt_error(
            attempt_directory,
            task_id,
            run_id,
            adapter_error,
            phase="validate_response",
            response_received=True,
        )
        raise adapter_error from error
    normalized: dict[str, Any] = {
        "draft_id": raw_response["draft_ref"],
        "status": "accepted",
        "preview_url": raw_response["preview"],
        "adapter": raw_response["adapter"],
    }
    validate_record("delivery-response", normalized)
    write_immutable_bytes(
        task_directory / "delivery" / "response-raw.json",
        raw_response_bytes,
    )
    write_immutable_bytes(
        task_directory / "delivery" / "response.json", _json_bytes(normalized)
    )
    return raw_response, normalized


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_attempt_error(
    attempt_directory: Path,
    task_id: str,
    run_id: str,
    error: BlogAdapterError,
    *,
    phase: str,
    response_received: bool,
) -> None:
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "attempt_version": 1,
        "task_id": task_id,
        "run_id": run_id,
        "phase": phase,
        "error_category": error.category,
        "error_code": error.code,
        "message": str(error),
        "response_received": response_received,
    }
    validate_record("delivery-attempt-error", record)
    write_immutable_bytes(attempt_directory / "error.json", _json_bytes(record))
