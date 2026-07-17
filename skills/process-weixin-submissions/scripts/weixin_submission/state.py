from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .schema_validation import (
    SchemaValidationError,
    allowed_transitions,
    validate_record,
)
from .storage import new_id, read_json, utc_now, write_json


def save_record(record_type: str, path: Path, value: dict[str, Any]) -> None:
    validate_record(record_type, value)
    write_json(path, value)


def load_record(record_type: str, path: Path) -> dict[str, Any]:
    if record_type == "task":
        return load_effective_task(path)
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
    state_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events_directory = task_directory / "events"
    existing = (
        sorted(events_directory.glob("*.json")) if events_directory.exists() else []
    )
    sequence = len(existing) + 1
    event = {
        "schema_version": 2,
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
        "state_after": deepcopy(state_after),
    }
    validate_record("event", event)
    path = events_directory / f"{sequence:06d}-{event['event_id']}.json"
    if path.exists():
        raise SchemaValidationError(f"Event path already exists: {path}")
    write_json(path, event)
    return event


def commit_task_state(
    task_directory: Path,
    task_record: dict[str, Any],
    run_id: str,
    event_type: str,
    *,
    milestone: str | None = None,
    operation: str | None = None,
    outcome: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    validate_record("task", task_record)
    append_task_event(
        task_directory,
        str(task_record["task_id"]),
        run_id,
        event_type,
        milestone=milestone,
        operation=operation,
        outcome=outcome,
        details=details,
        state_after=task_record,
    )
    save_record("task", task_directory / "task.json", task_record)


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
    commit_task_state(
        task_directory,
        task_record,
        run_id,
        "milestone_committed",
        milestone=next_milestone,
    )


def load_effective_task(task_path: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] | None = None
    if task_path.exists():
        snapshot = read_json(task_path)
        validate_record("task", snapshot)

    latest_state: dict[str, Any] | None = None
    events_directory = task_path.parent / "events"
    if events_directory.exists():
        for expected_sequence, event_path in enumerate(
            sorted(events_directory.glob("*.json")), start=1
        ):
            event = read_json(event_path)
            validate_record("event", event)
            if event["sequence"] != expected_sequence:
                raise SchemaValidationError(
                    f"Task event sequence is not contiguous at {event_path}"
                )
            if event["task_id"] != task_path.parent.name:
                raise SchemaValidationError(
                    f"Event {event_path} does not belong to task {task_path.parent.name}"
                )
            state_after = event["state_after"]
            if isinstance(state_after, dict):
                _validate_state_event(latest_state, event, state_after)
                latest_state = state_after

    effective = latest_state or snapshot
    if effective is None:
        raise SchemaValidationError(f"Task has no committed state: {task_path.parent}")
    validate_record("task", effective)
    return effective


def _validate_state_event(
    previous: dict[str, Any] | None,
    event: dict[str, Any],
    state_after: dict[str, Any],
) -> None:
    if state_after["task_id"] != event["task_id"]:
        raise SchemaValidationError(
            "Event state_after task_id does not match event task_id"
        )
    event_type = event["type"]
    milestone = state_after["milestone"]
    if event_type == "milestone_committed":
        if event["milestone"] != milestone:
            raise SchemaValidationError(
                "milestone_committed event does not match state_after milestone"
            )
        if previous is None:
            if milestone != "task_created":
                raise SchemaValidationError(
                    "First committed task state must be task_created"
                )
            if state_after["created_in_run"] != event["run_id"]:
                raise SchemaValidationError(
                    "task_created state must reference the event's run"
                )
            if state_after["retry_generation"] != 0:
                raise SchemaValidationError(
                    "task_created retry_generation must be zero"
                )
        elif milestone not in allowed_transitions().get(previous["milestone"], ()):
            raise SchemaValidationError(
                f"Illegal task event transition: {previous['milestone']} -> {milestone}"
            )
    elif previous is None:
        raise SchemaValidationError("First state-changing event must create the task")
    elif milestone != previous["milestone"]:
        raise SchemaValidationError(
            f"Event {event_type} cannot change milestone to {milestone}"
        )

    if previous is not None:
        immutable_fields = (
            "task_id",
            "created_in_run",
            "created_at",
            "target_id",
            "requirements",
        )
        changed = [
            field for field in immutable_fields if state_after[field] != previous[field]
        ]
        if changed:
            raise SchemaValidationError(
                f"Task state event changed immutable fields {changed}"
            )
        previous_generation = previous["retry_generation"]
        next_generation = state_after["retry_generation"]
        if event_type == "retry_enabled":
            if next_generation != previous_generation + 1:
                raise SchemaValidationError(
                    "retry_enabled must increment retry_generation exactly once"
                )
            previous_blocker = previous["blocker"]
            next_blocker = state_after["blocker"]
            if (
                not isinstance(previous_blocker, dict)
                or previous_blocker.get("kind") != "retry_exhausted"
                or not isinstance(next_blocker, dict)
                or next_blocker.get("kind") != "retry_pending"
            ):
                raise SchemaValidationError(
                    "retry_enabled requires retry_exhausted -> retry_pending"
                )
            if next_blocker["attempts_used"] != 0:
                raise SchemaValidationError(
                    "retry_enabled must reset attempts_used to zero"
                )
            stable_retry_fields = (
                "operation",
                "error_category",
                "error_code",
                "retry_budget",
            )
            changed_retry_fields = [
                field
                for field in stable_retry_fields
                if next_blocker[field] != previous_blocker[field]
            ]
            if changed_retry_fields:
                raise SchemaValidationError(
                    f"retry_enabled changed retry fields {changed_retry_fields}"
                )
        elif next_generation != previous_generation:
            raise SchemaValidationError(
                f"Event {event_type} cannot change retry_generation"
            )


def reconcile_task_projections(repository: Path) -> list[str]:
    reconciled: list[str] = []
    for task_directory in sorted((repository / "tasks").iterdir()):
        if not task_directory.is_dir():
            continue
        task_path = task_directory / "task.json"
        try:
            effective = load_effective_task(task_path)
        except SchemaValidationError:
            continue
        persisted = read_json(task_path) if task_path.exists() else None
        if persisted != effective:
            save_record("task", task_path, effective)
            reconciled.append(str(effective["task_id"]))

        raw_intake_path = task_directory / "raw" / "intake.json"
        if not raw_intake_path.exists():
            raw_intake = _committed_raw_intake(task_directory)
            if raw_intake is not None:
                write_json(raw_intake_path, raw_intake)
    return reconciled


def _committed_raw_intake(task_directory: Path) -> dict[str, Any] | None:
    events_directory = task_directory / "events"
    if not events_directory.exists():
        return None
    for event_path in sorted(events_directory.glob("*.json")):
        event = read_json(event_path)
        validate_record("event", event)
        if (
            event["type"] != "milestone_committed"
            or event["milestone"] != "task_created"
        ):
            continue
        raw_intake = event["details"].get("raw_intake")
        if isinstance(raw_intake, dict):
            return raw_intake
    return None
