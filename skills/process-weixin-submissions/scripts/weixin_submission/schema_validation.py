from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SCHEMA_DIRECTORY = Path(__file__).resolve().parents[2] / "schemas"


class SchemaValidationError(Exception):
    """A persisted record does not conform to its JSON Schema."""


@lru_cache(maxsize=None)
def load_schema(record_type: str) -> dict[str, Any]:
    path = SCHEMA_DIRECTORY / f"{record_type}.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise SchemaValidationError(f"Cannot load schema for {record_type}: {error}") from error
    if not isinstance(schema, dict):
        raise SchemaValidationError(f"Schema for {record_type} must be an object")
    return schema


def validate_record(record_type: str, value: dict[str, Any]) -> None:
    schema = load_schema(record_type)
    _validate(value, schema, record_type)
    if record_type == "task":
        _validate_task_invariants(value, schema)
    if record_type == "run":
        _validate_discriminated_invariants(value, schema, "status", "x-status-invariants")
    if record_type == "event":
        _validate_discriminated_invariants(value, schema, "type", "x-type-invariants")
        milestone = value.get("milestone")
        if isinstance(milestone, str) and milestone not in milestones():
            raise SchemaValidationError(f"event: unknown milestone {milestone!r}")
        state_after = value.get("state_after")
        if isinstance(state_after, dict):
            validate_record("task", state_after)


def allowed_transitions() -> dict[str, tuple[str, ...]]:
    transitions = load_schema("task").get("x-allowed-transitions")
    if not isinstance(transitions, dict):
        raise SchemaValidationError("Task schema is missing x-allowed-transitions")
    result: dict[str, tuple[str, ...]] = {}
    for current, following in transitions.items():
        if not isinstance(current, str) or not isinstance(following, list) or not all(
            isinstance(item, str) for item in following
        ):
            raise SchemaValidationError("Task transition metadata is invalid")
        result[current] = tuple(following)
    return result


def milestones() -> tuple[str, ...]:
    task_schema = load_schema("task")
    properties = task_schema.get("properties")
    if not isinstance(properties, dict):
        raise SchemaValidationError("Task schema is missing properties")
    milestone_schema = properties.get("milestone")
    if not isinstance(milestone_schema, dict):
        raise SchemaValidationError("Task schema is missing milestone")
    values = milestone_schema.get("enum")
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise SchemaValidationError("Task milestone enum is invalid")
    return tuple(values)


def _validate(value: Any, schema: dict[str, Any], location: str) -> None:
    if "oneOf" in schema:
        alternatives = schema["oneOf"]
        if not isinstance(alternatives, list):
            raise SchemaValidationError(f"{location}: oneOf must be an array")
        matches = 0
        for alternative in alternatives:
            try:
                _validate(value, alternative, location)
            except SchemaValidationError:
                continue
            matches += 1
        if matches != 1:
            raise SchemaValidationError(
                f"{location}: expected exactly one schema match, got {matches}"
            )
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(value, item) for item in types):
            raise SchemaValidationError(
                f"{location}: expected type {expected_type}, got {type(value).__name__}"
            )

    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(f"{location}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{location}: value {value!r} is not in enum")
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema:
        if value < schema["minimum"]:
            raise SchemaValidationError(f"{location}: value is below minimum")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [field for field in required if field not in value]
        if missing:
            raise SchemaValidationError(f"{location}: missing required fields {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise SchemaValidationError(f"{location}: unknown fields {unknown}")
        for field, field_value in value.items():
            field_schema = properties.get(field)
            if isinstance(field_schema, dict):
                _validate(field_value, field_schema, f"{location}.{field}")

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{location}[{index}]")


def _matches_type(value: Any, expected: object) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


def _validate_task_invariants(value: dict[str, Any], schema: dict[str, Any]) -> None:
    invariants = schema.get("x-milestone-invariants")
    if not isinstance(invariants, dict):
        raise SchemaValidationError("Task schema is missing x-milestone-invariants")
    milestone = value.get("milestone")
    invariant = invariants.get(milestone)
    if not isinstance(invariant, dict):
        raise SchemaValidationError(f"task: no invariant for milestone {milestone!r}")

    blocker = value.get("blocker")
    blocker_kind = "none" if blocker is None else blocker.get("kind")
    allowed_blockers = invariant.get("allowed_blockers")
    if not isinstance(allowed_blockers, list) or blocker_kind not in allowed_blockers:
        raise SchemaValidationError(
            f"task: illegal blocker {blocker_kind!r} at milestone {milestone!r}"
        )

    expected_external_draft = invariant.get("external_draft")
    external_draft = value.get("external_draft")
    if expected_external_draft == "null" and external_draft is not None:
        raise SchemaValidationError(
            f"task: external_draft must be null at milestone {milestone!r}"
        )
    if expected_external_draft == "object" and not isinstance(external_draft, dict):
        raise SchemaValidationError(
            f"task: external_draft must be an object at milestone {milestone!r}"
        )

    if isinstance(blocker, dict) and blocker.get("kind") in (
        "retry_pending",
        "retry_exhausted",
    ):
        if blocker["retry_generation"] != value.get("retry_generation"):
            raise SchemaValidationError(
                "task: blocker retry_generation must match task retry_generation"
            )
        attempts_used = blocker["attempts_used"]
        retry_budget = blocker["retry_budget"]
        retry_invariants = schema.get("x-retry-blocker-invariants")
        if not isinstance(retry_invariants, dict):
            raise SchemaValidationError(
                "Task schema is missing x-retry-blocker-invariants"
            )
        rule = retry_invariants.get(blocker["kind"])
        if rule == "attempts_used_below_budget" and attempts_used >= retry_budget:
            raise SchemaValidationError(
                "task: retry_pending attempts_used must be below retry_budget"
            )
        if rule == "attempts_used_equals_budget" and attempts_used != retry_budget:
            raise SchemaValidationError(
                "task: retry_exhausted attempts_used must equal retry_budget"
            )


def _validate_discriminated_invariants(
    value: dict[str, Any],
    schema: dict[str, Any],
    discriminator: str,
    extension: str,
) -> None:
    invariants = schema.get(extension)
    if not isinstance(invariants, dict):
        raise SchemaValidationError(f"Schema is missing {extension}")
    discriminator_value = value.get(discriminator)
    invariant = invariants.get(discriminator_value)
    if not isinstance(invariant, dict):
        raise SchemaValidationError(
            f"No invariant for {discriminator} {discriminator_value!r}"
        )
    for field, expected in invariant.items():
        actual = value.get(field)
        if expected == "any":
            continue
        if expected in ("null", "string", "object") and not _matches_type(
            actual, expected
        ):
            raise SchemaValidationError(
                f"{discriminator} {discriminator_value!r}: {field} must be {expected}"
            )
        if expected not in ("any", "null", "string", "object") and actual != expected:
            raise SchemaValidationError(
                f"{discriminator} {discriminator_value!r}: {field} must be {expected!r}"
            )
