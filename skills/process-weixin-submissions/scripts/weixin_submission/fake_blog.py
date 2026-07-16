from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .delivery import BlogAdapterError, BlogErrorCategory
from .schema_validation import SchemaValidationError, validate_record
from .storage import WorkflowError, read_json, write_bytes, write_json


class FakeBlogAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def adapter_id(self) -> str:
        return "fake"

    def map_target(self, source_id: str) -> str:
        return f"fake-target:{source_id}"

    def upload_image(self, expected_sha256: str, content: bytes) -> str:
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise BlogAdapterError(
                BlogErrorCategory.INVALID_REQUEST,
                "image_hash_mismatch",
                "Image bytes do not match the canonical artifact hash",
            )
        asset_id = f"asset-{actual_sha256}"
        uploads = self.directory / "uploads"
        record_path = uploads / f"{asset_id}.json"
        upload_requests = 1
        if record_path.exists():
            prior = read_json(record_path)
            prior_requests = prior.get("upload_requests")
            if not isinstance(prior_requests, int):
                raise WorkflowError("Fake Blog upload record has invalid request count")
            upload_requests = prior_requests + 1
        write_bytes(uploads / f"{asset_id}.bin", content)
        write_json(
            record_path,
            {
                "asset_id": asset_id,
                "sha256": actual_sha256,
                "upload_requests": upload_requests,
            },
        )
        return asset_id

    def create_draft(self, request: dict[str, Any]) -> object:
        idempotency_key = request.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise BlogAdapterError(
                BlogErrorCategory.INVALID_REQUEST,
                "missing_idempotency_key",
                "Draft request requires an idempotency key",
            )
        idempotency_path = self.directory / "idempotency" / f"{idempotency_key}.json"
        if idempotency_path.exists():
            prior = read_json(idempotency_path)
            if prior.get("request") != request:
                raise BlogAdapterError(
                    BlogErrorCategory.INVALID_REQUEST,
                    "idempotency_conflict",
                    "Idempotency key was reused with a different request",
                )
            response = prior.get("response")
            return response

        configured_failure = self._take_configured_failure()
        if configured_failure is not None and configured_failure.get("effect") not in (
            "accept_then_timeout",
        ):
            self._raise_failure(configured_failure)
        drafts = self.directory / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        existing = sorted(drafts.glob("draft-*.json"))
        draft_id = f"draft-{len(existing) + 1:06d}"
        has_configured_response, configured_response = (
            self._take_configured_response()
        )
        raw_response: object = (
            configured_response
            if has_configured_response
            else {
                "draft_ref": draft_id,
                "state": "draft_accepted",
                "preview": f"https://blog.example.test/drafts/{draft_id}",
                "adapter": "fake",
            }
        )
        write_json(
            drafts / f"{draft_id}.json",
            {"request": request, "response": raw_response},
        )
        write_json(
            idempotency_path,
            {"request": request, "response": raw_response},
        )
        if configured_failure is not None:
            self._raise_failure(configured_failure)
        return raw_response

    def normalize_draft_response(self, raw_response: object) -> dict[str, Any]:
        if not isinstance(raw_response, dict):
            raise BlogAdapterError(
                BlogErrorCategory.INVALID_RESPONSE,
                "blog_response_invalid",
                "Fake Blog response must be a JSON object",
            )
        if raw_response.get("state") == "rejected":
            raise BlogAdapterError(
                BlogErrorCategory.REJECTED_RESPONSE,
                "draft_rejected",
                "Blog service explicitly rejected the draft",
            )
        try:
            validate_record("fake-blog-response", raw_response)
            draft_ref = raw_response.get("draft_ref")
            if not isinstance(draft_ref, str) or not draft_ref.strip():
                raise SchemaValidationError(
                    "fake-blog-response.draft_ref must be non-empty"
                )
            preview = raw_response.get("preview")
            if not isinstance(preview, str) or not preview.startswith("https://"):
                raise SchemaValidationError(
                    "fake-blog-response.preview must use https"
                )
        except SchemaValidationError as error:
            raise BlogAdapterError(
                BlogErrorCategory.INVALID_RESPONSE,
                "blog_response_invalid",
                str(error),
            ) from error
        return {
            "draft_id": draft_ref,
            "status": "accepted",
            "preview_url": preview,
            "adapter": self.adapter_id,
        }

    def _take_configured_failure(self) -> dict[str, Any] | None:
        control_path = self.directory / "control.json"
        if not control_path.exists():
            return None
        control = read_json(control_path)
        failures = control.get("create_draft_failures", [])
        if not isinstance(failures, list) or not failures:
            return None
        failure = failures.pop(0)
        if not isinstance(failure, dict):
            raise WorkflowError("Fake Blog failure entry must be an object")
        control["create_draft_failures"] = failures
        write_json(control_path, control)
        return failure

    def _take_configured_response(self) -> tuple[bool, object]:
        control_path = self.directory / "control.json"
        if not control_path.exists():
            return False, None
        control = read_json(control_path)
        responses = control.get("create_draft_responses", [])
        if not isinstance(responses, list) or not responses:
            return False, None
        response = responses.pop(0)
        control["create_draft_responses"] = responses
        write_json(control_path, control)
        return True, response

    def _raise_failure(self, failure: dict[str, Any]) -> None:
        category = failure.get("category")
        code = failure.get("code")
        message = failure.get("message")
        if not isinstance(category, str) or not isinstance(code, str) or not isinstance(
            message, str
        ):
            raise WorkflowError("Fake Blog failure fields must be strings")
        try:
            typed_category = BlogErrorCategory(category)
        except ValueError as error:
            raise WorkflowError(
                f"Unknown Fake Blog error category: {category}"
            ) from error
        raise BlogAdapterError(typed_category, code, message)
