from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .storage import WorkflowError, read_json, write_bytes, write_json


class BlogAdapterError(WorkflowError):
    def __init__(self, category: str, code: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.code = code


class FakeBlogAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def map_target(self, source_id: str) -> str:
        return f"fake-target:{source_id}"

    def upload_image(self, expected_sha256: str, content: bytes) -> str:
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise BlogAdapterError(
                "invalid_request",
                "image_hash_mismatch",
                "Image bytes do not match the canonical artifact hash",
            )
        asset_id = f"asset-{actual_sha256}"
        uploads = self.directory / "uploads"
        write_bytes(uploads / f"{asset_id}.bin", content)
        write_json(
            uploads / f"{asset_id}.json",
            {"asset_id": asset_id, "sha256": actual_sha256},
        )
        return asset_id

    def create_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        idempotency_key = request.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise BlogAdapterError(
                "invalid_request",
                "missing_idempotency_key",
                "Draft request requires an idempotency key",
            )
        idempotency_path = self.directory / "idempotency" / f"{idempotency_key}.json"
        if idempotency_path.exists():
            prior = read_json(idempotency_path)
            if prior.get("request") != request:
                raise BlogAdapterError(
                    "invalid_request",
                    "idempotency_conflict",
                    "Idempotency key was reused with a different request",
                )
            response = prior.get("response")
            if not isinstance(response, dict):
                raise WorkflowError("Fake Blog idempotency record has no response")
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
        raw_response = self._take_configured_response() or {
            "draft_ref": draft_id,
            "state": "draft_accepted",
            "preview": f"https://blog.example.test/drafts/{draft_id}",
            "adapter": "fake",
        }
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

    def _take_configured_response(self) -> dict[str, Any] | None:
        control_path = self.directory / "control.json"
        if not control_path.exists():
            return None
        control = read_json(control_path)
        responses = control.get("create_draft_responses", [])
        if not isinstance(responses, list) or not responses:
            return None
        response = responses.pop(0)
        if not isinstance(response, dict):
            raise WorkflowError("Fake Blog response entry must be an object")
        control["create_draft_responses"] = responses
        write_json(control_path, control)
        return response

    def _raise_failure(self, failure: dict[str, Any]) -> None:
        category = failure.get("category")
        code = failure.get("code")
        message = failure.get("message")
        if not isinstance(category, str) or not isinstance(code, str) or not isinstance(
            message, str
        ):
            raise WorkflowError("Fake Blog failure fields must be strings")
        raise BlogAdapterError(category, code, message)
