from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema_validation import validate_record


REPOSITORY_VERSION = 2
VALIDATION_SCOPE = "ticket_03_durable_workflow"


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
        validate_record("repository", existing_metadata)
        if existing_metadata.get("repository_version") != REPOSITORY_VERSION:
            raise WorkflowError("Unsupported repository version")
        return existing_metadata

    metadata: dict[str, object] = {
        "repository_version": REPOSITORY_VERSION,
        "created_at": utc_now(),
        "validation_scope": VALIDATION_SCOPE,
        "intake": None,
        "pending_window": None,
    }
    validate_record("repository", metadata)
    write_json(metadata_path, metadata)
    return metadata


def repository_status(repository: Path) -> dict[str, object]:
    metadata = read_json(repository / "repository.json")
    validate_record("repository", metadata)
    from .state import load_record
    from .writer_lock import describe_writer_lock

    run_status_counts: dict[str, int] = {}
    run_ids: set[str] = set()
    for run_directory in sorted((repository / "runs").iterdir()):
        if not run_directory.is_dir():
            continue
        run = load_record("run", run_directory / "run.json")
        run_ids.add(str(run["run_id"]))
        status = str(run["status"])
        run_status_counts[status] = run_status_counts.get(status, 0) + 1

    milestone_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    task_count = 0
    for task_directory in sorted((repository / "tasks").iterdir()):
        if not task_directory.is_dir():
            continue
        task_count += 1
        task = load_record("task", task_directory / "task.json")
        events_directory = task_directory / "events"
        if events_directory.exists():
            for event_path in sorted(events_directory.glob("*.json")):
                event = load_record("event", event_path)
                if event["task_id"] != task["task_id"]:
                    raise WorkflowError(
                        f"Event {event_path} does not belong to task {task['task_id']}"
                    )
                if event["run_id"] not in run_ids:
                    raise WorkflowError(
                        f"Event {event_path} references missing run {event['run_id']}"
                    )
        milestone = str(task["milestone"])
        milestone_counts[milestone] = milestone_counts.get(milestone, 0) + 1
        blocker = task["blocker"]
        if isinstance(blocker, dict):
            kind = str(blocker["kind"])
            blocker_counts[kind] = blocker_counts.get(kind, 0) + 1

    return {
        "status": "ok",
        "repository_version": metadata["repository_version"],
        "validation_scope": metadata["validation_scope"],
        "run_count": len(run_ids),
        "task_count": task_count,
        "milestones": milestone_counts,
        "blockers": blocker_counts,
        "run_statuses": run_status_counts,
        "writer_lock": describe_writer_lock(repository),
    }
