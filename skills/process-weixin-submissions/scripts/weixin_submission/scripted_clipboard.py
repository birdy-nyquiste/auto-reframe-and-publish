from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

from .storage import WorkflowError, new_id, read_json, write_json


class ScriptedClipboard:
    """File-backed clipboard fixture with explicit exclusive ownership."""

    def __init__(self, path: Path, operation: str) -> None:
        self.path = path
        self.owner_id = new_id(f"clipboard_{operation}")
        self._active = False

    def __enter__(self) -> ScriptedClipboard:
        record = self._load_or_initialize()
        existing_owner = record["owner_id"]
        if existing_owner is not None:
            raise WorkflowError(
                f"The scripted clipboard is already owned by {existing_owner}"
            )
        self._active = True
        self._write(owner_id=self.owner_id, text="")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._active:
            self._write(owner_id=None, text="")
            self._active = False

    def paste_text(self, value: str) -> None:
        self._require_owned()
        self._write(owner_id=self.owner_id, text=value)

    def read_for_paste(self) -> str:
        record = self._require_owned()
        return str(record["text"])

    def clear(self) -> None:
        self._require_owned()
        self._write(owner_id=self.owner_id, text="")

    def _load_or_initialize(self) -> dict[str, Any]:
        if not self.path.exists():
            self._write(owner_id=None, text="")
        record = read_json(self.path)
        expected_fields = {"schema_version", "owner_id", "text"}
        if set(record) != expected_fields:
            raise WorkflowError(
                "Scripted clipboard fields must be schema_version, owner_id, and text"
            )
        if record["schema_version"] != 1:
            raise WorkflowError("Scripted clipboard schema_version must be 1")
        if record["owner_id"] is not None and not isinstance(
            record["owner_id"], str
        ):
            raise WorkflowError("Scripted clipboard owner_id must be string or null")
        if not isinstance(record["text"], str):
            raise WorkflowError("Scripted clipboard text must be a string")
        return record

    def _require_owned(self) -> dict[str, Any]:
        if not self._active:
            raise WorkflowError("Scripted clipboard is not active")
        record = self._load_or_initialize()
        if record["owner_id"] != self.owner_id:
            raise WorkflowError("Scripted clipboard ownership changed during operation")
        return record

    def _write(self, *, owner_id: str | None, text: str) -> None:
        write_json(
            self.path,
            {
                "schema_version": 1,
                "owner_id": owner_id,
                "text": text,
            },
        )
