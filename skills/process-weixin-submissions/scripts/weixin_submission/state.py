from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, allowed_transitions, validate_record
from .storage import new_id, read_json, utc_now, write_json


def save_record(record_type: str, path: Path, value: dict[str, Any]) -> None:
    validate_record(record_type, value)
    write_json(path, value)


def load_record(record_type: str, path: Path) -> dict[str, Any]:
    value = read_json(path)
    validate_record(record_type, value)
    return value


def append_task_event(
    task_directory: Path,
    task_id: str,
    run_id: str,
    event_type: str,
    *,
    milestone: str | None = None,
    operation: str | None = None,
    outcome: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events_directory = task_directory / "events"
    existing = sorted(events_directory.glob("*.json")) if events_directory.exists() else []
    sequence = len(existing) + 1
    event = {
        "schema_version": 1,
        "event_id": new_id("event"),
        "sequence": sequence,
        "task_id": task_id,
        "run_id": run_id,
        "occurred_at": utc_now(),
        "type": event_type,
        "milestone": milestone,
        "operation": operation,
        "outcome": outcome,
        "details": details or {},
    }
    validate_record("event", event)
    path = events_directory / f"{sequence:06d}-{event['event_id']}.json"
    if path.exists():
        raise SchemaValidationError(f"Event path already exists: {path}")
    write_json(path, event)
    return event


def commit_task_milestone(
    task_directory: Path,
    task_record: dict[str, Any],
    next_milestone: str,
    run_id: str,
) -> None:
    current = task_record["milestone"]
    if next_milestone not in allowed_transitions().get(current, ()):
        raise SchemaValidationError(
            f"Illegal task transition: {current} -> {next_milestone}"
        )
    task_record["milestone"] = next_milestone
    task_record["updated_at"] = utc_now()
    save_record("task", task_directory / "task.json", task_record)
    append_task_event(
        task_directory,
        task_record["task_id"],
        run_id,
        "milestone_committed",
        milestone=next_milestone,
    )
