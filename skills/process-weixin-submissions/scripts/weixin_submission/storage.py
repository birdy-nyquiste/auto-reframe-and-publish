from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_VERSION = 1
VALIDATION_SCOPE = "ticket_02_scripted_intake"


class WorkflowError(Exception):
    """An operator-facing validation or workflow error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowError(f"JSON file does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise WorkflowError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def initialize_repository(repository: Path) -> dict[str, object]:
    repository.mkdir(parents=True, exist_ok=True)
    (repository / "runs").mkdir(exist_ok=True)
    (repository / "tasks").mkdir(exist_ok=True)
    metadata_path = repository / "repository.json"
    if metadata_path.exists():
        existing_metadata = read_json(metadata_path)
        if existing_metadata.get("repository_version") != REPOSITORY_VERSION:
            raise WorkflowError("Unsupported repository version")
        return existing_metadata

    metadata: dict[str, object] = {
        "repository_version": REPOSITORY_VERSION,
        "created_at": utc_now(),
        "validation_scope": VALIDATION_SCOPE,
    }
    write_json(metadata_path, metadata)
    return metadata


def repository_status(repository: Path) -> dict[str, object]:
    metadata = read_json(repository / "repository.json")
    run_count = sum(1 for path in (repository / "runs").iterdir() if path.is_dir())
    task_count = sum(1 for path in (repository / "tasks").iterdir() if path.is_dir())
    return {
        "status": "ok",
        "repository_version": metadata["repository_version"],
        "validation_scope": metadata["validation_scope"],
        "run_count": run_count,
        "task_count": task_count,
    }
