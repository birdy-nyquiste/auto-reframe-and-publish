from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import WorkflowError, read_json, write_json


class BlogAdapterError(WorkflowError):
    def __init__(self, category: str, code: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.code = code


class FakeBlogAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def create_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        self._raise_configured_failure()
        drafts = self.directory / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        existing = sorted(drafts.glob("draft-*.json"))
        draft_id = f"draft-{len(existing) + 1:06d}"
        response = {
            "draft_id": draft_id,
            "status": "accepted",
            "preview_url": f"https://blog.example.test/drafts/{draft_id}",
            "adapter": "fake",
        }
        write_json(drafts / f"{draft_id}.json", {"request": request, "response": response})
        return response

    def _raise_configured_failure(self) -> None:
        control_path = self.directory / "control.json"
        if not control_path.exists():
            return
        control = read_json(control_path)
        failures = control.get("create_draft_failures", [])
        if not isinstance(failures, list) or not failures:
            return
        failure = failures.pop(0)
        if not isinstance(failure, dict):
            raise WorkflowError("Fake Blog failure entry must be an object")
        control["create_draft_failures"] = failures
        write_json(control_path, control)
        category = failure.get("category")
        code = failure.get("code")
        message = failure.get("message")
        if not isinstance(category, str) or not isinstance(code, str) or not isinstance(
            message, str
        ):
            raise WorkflowError("Fake Blog failure fields must be strings")
        raise BlogAdapterError(category, code, message)
