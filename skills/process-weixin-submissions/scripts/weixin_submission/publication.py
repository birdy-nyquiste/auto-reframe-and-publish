from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from .rewrite import RewriteArtifact, load_rewrite_artifact
from .schema_validation import (
    SchemaValidationError,
    publication_allowed_transitions,
    validate_record,
)
from .state import load_record, save_record
from .storage import (
    WorkflowError,
    new_id,
    read_json,
    utc_now,
    write_immutable_bytes,
    write_json,
)
from .submission import SCHEMA_VERSION


class PublicationAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    @property
    def destination_id(self) -> str: ...

    def map_target(self, source_id: str) -> dict[str, Any]: ...

    def validate_request(self, request: dict[str, Any]) -> None: ...

    def publish(self, request: dict[str, Any]) -> object: ...

    def confirm(self, request: dict[str, Any]) -> object: ...

    def normalize_response(self, raw_response: object) -> dict[str, Any]: ...


class PublicationBlockerKind(str, Enum):
    NEEDS_CONFIGURATION = "needs_configuration"
    PERMANENT_FAILURE = "permanent_failure"
    OUTCOME_UNKNOWN = "outcome_unknown"


class PublicationError(WorkflowError):
    def __init__(
        self,
        blocker_kind: PublicationBlockerKind,
        code: str,
        message: str,
        raw_response: object | None = None,
    ) -> None:
        super().__init__(message)
        self.blocker_kind = blocker_kind
        self.code = code
        self.raw_response = raw_response


class FakePublicationAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def adapter_id(self) -> str:
        return "fake_publication"

    @property
    def destination_id(self) -> str:
        return self.directory.resolve().as_uri()

    def map_target(self, source_id: str) -> dict[str, Any]:
        return {"authorName": f"fake-author:{source_id}"}

    def validate_request(self, request: dict[str, Any]) -> None:
        return

    def publish(self, request: dict[str, Any]) -> object:
        configured_failure = self._take_failure()
        if configured_failure is not None:
            try:
                blocker_kind = PublicationBlockerKind(
                    str(configured_failure.get("kind", "permanent_failure"))
                )
            except ValueError as error:
                raise WorkflowError(
                    "Fake publication failure has an invalid blocker kind"
                ) from error
            raise PublicationError(
                blocker_kind,
                str(configured_failure.get("code", "fake_publication_failed")),
                str(configured_failure.get("message", "Fake publication failed")),
            )
        publication_id = str(request["publication_id"])
        idempotency_path = self.directory / "idempotency" / f"{publication_id}.json"
        if idempotency_path.exists():
            prior = read_json(idempotency_path)
            if prior.get("request") != request:
                raise WorkflowError(
                    "Fake publication ID was reused with another request"
                )
            return prior["response"]
        response = {
            "external_id": f"post-{publication_id}",
            "status": "published",
            "public_url": f"https://blog.example.test/posts/{request['slug']}",
            "slug": request["slug"],
            "adapter": self.adapter_id,
        }
        write_json(
            self.directory / "posts" / f"{publication_id}.json",
            {"request": request, "response": response},
        )
        write_json(idempotency_path, {"request": request, "response": response})
        return response

    def confirm(self, request: dict[str, Any]) -> object:
        publication_id = str(request["publication_id"])
        idempotency_path = self.directory / "idempotency" / f"{publication_id}.json"
        if not idempotency_path.exists():
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                "publication_outcome_unknown",
                "The prior fake publication attempt could not be confirmed",
            )
        prior = read_json(idempotency_path)
        if prior.get("request") != request:
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                "publication_outcome_unknown",
                "The prior fake publication request no longer matches",
            )
        return prior["response"]

    def normalize_response(self, raw_response: object) -> dict[str, Any]:
        if not isinstance(raw_response, dict):
            raise WorkflowError("Fake publication response must be an object")
        normalized = dict(raw_response)
        validate_record("publication-response", normalized)
        return normalized

    def _take_failure(self) -> dict[str, Any] | None:
        control_path = self.directory / "control.json"
        if not control_path.exists():
            return None
        control = read_json(control_path)
        failures = control.get("publish_failures", [])
        if not isinstance(failures, list) or not failures:
            return None
        failure = failures.pop(0)
        if not isinstance(failure, dict):
            raise WorkflowError("Fake publication failure must be an object")
        control["publish_failures"] = failures
        write_json(control_path, control)
        return failure


def publish_rewrite(
    repository: Path,
    task_id: str,
    run_id: str,
    adapter: PublicationAdapter,
    before_send: Callable[[], None] | None = None,
    after_send_started: Callable[[], None] | None = None,
    after_response_received: Callable[[], None] | None = None,
) -> tuple[str, dict[str, Any]]:
    task_directory = repository / "tasks" / task_id
    task = load_record("task", task_directory / "task.json")
    if task["milestone"] != "rewrite_artifact_ready" or task["blocker"] is not None:
        raise WorkflowError(f"Task {task_id} has no publishable rewrite artifact")
    target_id = task["target_id"]
    if not isinstance(target_id, str):
        raise WorkflowError(f"Task {task_id} has no target ID")
    artifact = load_rewrite_artifact(task_directory, target_id, task["requirements"])
    commit_bytes = (task_directory / "rewrite" / "commit.json").read_bytes()
    publication_id = new_id("publication")
    publication_directory = repository / "publications" / publication_id
    now = utc_now()
    publication: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "publication_id": publication_id,
        "created_in_run": run_id,
        "created_at": now,
        "updated_at": now,
        "task_id": task_id,
        "rewrite_commit_sha256": hashlib.sha256(commit_bytes).hexdigest(),
        "target_id": target_id,
        "slug": _slug(publication_id),
        "adapter": adapter.adapter_id,
        "milestone": "publication_created",
        "blocker": None,
        "external_result": None,
    }
    _commit_publication(
        publication_directory, publication, run_id, "milestone_committed"
    )

    if artifact.images:
        publication["blocker"] = {
            "kind": "needs_configuration",
            "error_code": "public_image_urls_missing",
            "message": "The rewrite contains local images without stable public URLs",
        }
        publication["updated_at"] = utc_now()
        _commit_publication(publication_directory, publication, run_id, "blocked")
        return publication_id, _result(publication)

    try:
        request = _request(publication, artifact, adapter)
    except PublicationError as error:
        _block(publication_directory, publication, run_id, error)
        return publication_id, _result(publication)
    request_bytes = _json_bytes(request)
    write_immutable_bytes(publication_directory / "request.json", request_bytes)
    write_immutable_bytes(
        publication_directory / "attempts" / run_id / "request.json", request_bytes
    )
    _write_attempt_marker(
        publication_directory / "attempts" / run_id / "prepared.json",
        "prepared",
        request_bytes,
    )
    publication["milestone"] = "request_ready"
    publication["updated_at"] = utc_now()
    _commit_publication(
        publication_directory, publication, run_id, "milestone_committed"
    )

    try:
        adapter.validate_request(request)
    except PublicationError as error:
        _record_publication_error(
            publication_directory, publication, run_id, error
        )
        return publication_id, _result(publication)
    if before_send is not None:
        before_send()
    return publication_id, _execute_post_attempt(
        publication_directory,
        publication,
        run_id,
        adapter,
        request,
        after_send_started=after_send_started,
        after_response_received=after_response_received,
    )


def resume_ready_publications(
    repository: Path,
    run_id: str,
    adapter: PublicationAdapter,
) -> list[tuple[str, dict[str, Any]]]:
    resumed: list[tuple[str, dict[str, Any]]] = []
    for publication_directory in sorted((repository / "publications").iterdir()):
        if not publication_directory.is_dir():
            continue
        try:
            publication = validate_publication_history(publication_directory)
        except (WorkflowError, SchemaValidationError, OSError):
            resumed.append(
                (
                    publication_directory.name,
                    {
                        "publication_id": publication_directory.name,
                        "task_id": "unknown",
                        "status": "permanent_failure",
                        "blocker_reason": "publication_integrity_failed",
                    },
                )
            )
            continue
        if (
            publication["milestone"] != "request_ready"
            or publication["blocker"] is not None
            or publication["adapter"] != adapter.adapter_id
        ):
            continue
        try:
            request, request_bytes, allow_post = _load_fixed_request(
                publication_directory, publication, adapter
            )
            attempt_directory = publication_directory / "attempts" / run_id
            write_immutable_bytes(attempt_directory / "request.json", request_bytes)
        except (WorkflowError, SchemaValidationError, OSError) as error:
            integrity_error = PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_integrity_failed",
                f"Durable publication evidence failed integrity validation: {error}",
            )
            _record_publication_error(
                publication_directory, publication, run_id, integrity_error
            )
            resumed.append((str(publication["publication_id"]), _result(publication)))
            continue
        if allow_post:
            try:
                adapter.validate_request(request)
            except PublicationError as error:
                _record_publication_error(
                    publication_directory, publication, run_id, error
                )
                resumed.append((str(publication["publication_id"]), _result(publication)))
                continue
            _write_attempt_marker(
                attempt_directory / "prepared.json",
                "prepared",
                request_bytes,
            )
            result = _execute_post_attempt(
                publication_directory,
                publication,
                run_id,
                adapter,
                request,
            )
        else:
            result = _execute_confirmation_attempt(
                publication_directory,
                publication,
                run_id,
                adapter,
                request,
            )
        resumed.append((str(publication["publication_id"]), result))
    return resumed


def _execute_post_attempt(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    adapter: PublicationAdapter,
    request: dict[str, Any],
    *,
    after_send_started: Callable[[], None] | None = None,
    after_response_received: Callable[[], None] | None = None,
) -> dict[str, Any]:
    attempt_directory = publication_directory / "attempts" / run_id
    request_bytes = _json_bytes(request)
    _write_attempt_marker(
        attempt_directory / "send-started.json",
        "send_started",
        request_bytes,
    )
    if after_send_started is not None:
        after_send_started()
    return _complete_publication_attempt(
        publication_directory,
        publication,
        run_id,
        adapter,
        request,
        adapter.publish,
        after_response_received,
    )


def _execute_confirmation_attempt(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    adapter: PublicationAdapter,
    request: dict[str, Any],
) -> dict[str, Any]:
    attempt_directory = publication_directory / "attempts" / run_id
    _write_attempt_marker(
        attempt_directory / "confirmation-started.json",
        "confirmation_started",
        _json_bytes(request),
    )
    return _complete_publication_attempt(
        publication_directory,
        publication,
        run_id,
        adapter,
        request,
        adapter.confirm,
    )


def _complete_publication_attempt(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    adapter: PublicationAdapter,
    request: dict[str, Any],
    invoke: Callable[[dict[str, Any]], object],
    after_response_received: Callable[[], None] | None = None,
) -> dict[str, Any]:
    attempt_directory = publication_directory / "attempts" / run_id
    try:
        raw_response = invoke(request)
    except PublicationError as error:
        _record_publication_error(publication_directory, publication, run_id, error)
        return _result(publication)
    if after_response_received is not None:
        after_response_received()
    raw_bytes = _json_bytes(raw_response)
    write_immutable_bytes(attempt_directory / "response-raw.json", raw_bytes)
    try:
        normalized = adapter.normalize_response(raw_response)
        validate_record("publication-response", normalized)
    except PublicationError as error:
        _record_publication_error(publication_directory, publication, run_id, error)
        return _result(publication)
    write_immutable_bytes(publication_directory / "response-raw.json", raw_bytes)
    write_immutable_bytes(
        publication_directory / "response.json", _json_bytes(normalized)
    )
    publication["external_result"] = normalized
    publication["milestone"] = "publication_confirmed"
    publication["updated_at"] = utc_now()
    _commit_publication(
        publication_directory, publication, run_id, "milestone_committed"
    )
    return _result(publication)


def _request(
    publication: dict[str, Any], artifact: RewriteArtifact, adapter: PublicationAdapter
) -> dict[str, Any]:
    request = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": 2,
        "operation": "publish_post",
        "publication_id": publication["publication_id"],
        "slug": publication["slug"],
        "target": {
            "source_id": artifact.target_id,
            "mapped_fields": adapter.map_target(artifact.target_id),
        },
        "title": artifact.title,
        "body_markdown": artifact.content,
        "images": [],
        "adapter": adapter.adapter_id,
        "destination": adapter.destination_id,
    }
    validate_record("publication-request", request)
    return request


def _commit_publication(
    directory: Path, publication: dict[str, Any], run_id: str, event_type: str
) -> None:
    validate_record("publication", publication)
    snapshot_path = directory / "publication.json"
    previous = read_json(snapshot_path) if snapshot_path.exists() else None
    if previous is None:
        if publication["milestone"] != "publication_created":
            raise WorkflowError("First publication state must be publication_created")
    else:
        validate_record("publication", previous)
        immutable_fields = (
            "publication_id",
            "created_in_run",
            "created_at",
            "task_id",
            "rewrite_commit_sha256",
            "target_id",
            "slug",
            "adapter",
        )
        changed = [
            field for field in immutable_fields if previous[field] != publication[field]
        ]
        if changed:
            raise WorkflowError(f"Publication changed immutable fields: {changed}")
        previous_milestone = str(previous["milestone"])
        next_milestone = str(publication["milestone"])
        if previous_milestone != next_milestone:
            transitions = publication_allowed_transitions()
            if next_milestone not in transitions[previous_milestone]:
                raise WorkflowError(
                    f"Illegal publication transition: {previous_milestone} -> {next_milestone}"
                )
    events = directory / "events"
    sequence = len(list(events.glob("*.json"))) + 1 if events.exists() else 1
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": new_id("event"),
        "sequence": sequence,
        "publication_id": publication["publication_id"],
        "run_id": run_id,
        "occurred_at": utc_now(),
        "type": event_type,
        "milestone": publication["milestone"],
        "details": {},
        "state_after": deepcopy(publication),
    }
    validate_record("publication-event", event)
    write_json(events / f"{sequence:06d}-{event['event_id']}.json", event)
    save_record("publication", snapshot_path, publication)


def validate_publication_history(directory: Path) -> dict[str, Any]:
    publication = read_json(directory / "publication.json")
    validate_record("publication", publication)
    latest: dict[str, Any] | None = None
    events = sorted((directory / "events").glob("*.json"))
    for expected_sequence, path in enumerate(events, start=1):
        event = read_json(path)
        validate_record("publication-event", event)
        if event["sequence"] != expected_sequence:
            raise WorkflowError(
                f"Publication event sequence is not contiguous at {path}"
            )
        if event["publication_id"] != directory.name:
            raise WorkflowError(
                f"Publication event {path} belongs to another publication"
            )
        state = event["state_after"]
        if latest is not None:
            immutable_fields = (
                "publication_id",
                "created_in_run",
                "created_at",
                "task_id",
                "rewrite_commit_sha256",
                "target_id",
                "slug",
                "adapter",
            )
            changed = [
                field for field in immutable_fields if latest[field] != state[field]
            ]
            if changed:
                raise WorkflowError(
                    f"Publication event changed immutable fields: {changed}"
                )
            previous_milestone = latest["milestone"]
            next_milestone = state["milestone"]
            allowed = set(publication_allowed_transitions()[previous_milestone])
            allowed.add(previous_milestone)
            if next_milestone not in allowed:
                raise WorkflowError(
                    f"Illegal publication event transition: {previous_milestone} -> {next_milestone}"
                )
        latest = state
    if latest is None or latest != publication:
        raise WorkflowError(
            f"Publication snapshot does not match its event history: {directory}"
        )
    return publication


def _result(publication: dict[str, Any]) -> dict[str, Any]:
    result = {
        "publication_id": publication["publication_id"],
        "task_id": publication["task_id"],
        "status": publication["milestone"],
    }
    if publication["blocker"] is not None:
        result["status"] = publication["blocker"]["kind"]
        result["blocker_reason"] = publication["blocker"]["error_code"]
    if publication["external_result"] is not None:
        result["public_url"] = publication["external_result"]["public_url"]
    return result


def _block(
    directory: Path,
    publication: dict[str, Any],
    run_id: str,
    error: PublicationError,
) -> None:
    publication["blocker"] = {
        "kind": error.blocker_kind.value,
        "error_code": error.code,
        "message": str(error),
    }
    publication["updated_at"] = utc_now()
    _commit_publication(directory, publication, run_id, "blocked")


def _record_publication_error(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    error: PublicationError,
) -> None:
    attempt_directory = publication_directory / "attempts" / run_id
    _write_raw_error_response(attempt_directory, error)
    _write_error(attempt_directory, error)
    _block(publication_directory, publication, run_id, error)


def _write_attempt_marker(path: Path, phase: str, request_bytes: bytes) -> None:
    marker = {
        "schema_version": 1,
        "phase": phase,
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
    }
    validate_record("publication-attempt-marker", marker)
    write_immutable_bytes(
        path,
        _json_bytes(marker),
    )


def _validate_request_identity(
    publication_directory: Path,
    publication: dict[str, Any],
    request: dict[str, Any],
    adapter: PublicationAdapter,
) -> None:
    expected = {
        "publication_id": publication["publication_id"],
        "slug": publication["slug"],
        "adapter": publication["adapter"],
    }
    observed = {field: request.get(field) for field in expected}
    if observed != expected:
        raise WorkflowError("Publication request does not match its durable identity")
    destination = request.get("destination")
    if not isinstance(destination, str):
        raise WorkflowError("Publication request lacks its fixed destination")
    if destination != adapter.destination_id:
        raise WorkflowError("Publication request destination does not match the adapter")
    repository = publication_directory.parents[1]
    task_directory = repository / "tasks" / str(publication["task_id"])
    task = load_record("task", task_directory / "task.json")
    if (
        task["task_id"] != publication["task_id"]
        or task["target_id"] != publication["target_id"]
        or task["milestone"] != "rewrite_artifact_ready"
        or task["blocker"] is not None
    ):
        raise WorkflowError("Publication no longer matches its content task")
    commit_bytes = (task_directory / "rewrite" / "commit.json").read_bytes()
    if hashlib.sha256(commit_bytes).hexdigest() != publication["rewrite_commit_sha256"]:
        raise WorkflowError("Publication rewrite commit hash no longer matches")
    artifact = load_rewrite_artifact(
        task_directory, str(publication["target_id"]), task["requirements"]
    )
    target = request.get("target")
    source_id = target.get("source_id") if isinstance(target, dict) else None
    if (
        source_id != artifact.target_id
        or request.get("title") != artifact.title
        or request.get("body_markdown") != artifact.content
        or request.get("images") != []
    ):
        raise WorkflowError("Publication request no longer matches its rewrite artifact")


def _load_fixed_request(
    publication_directory: Path,
    publication: dict[str, Any],
    adapter: PublicationAdapter,
) -> tuple[dict[str, Any], bytes, bool]:
    request_path = publication_directory / "request.json"
    request_bytes = request_path.read_bytes()
    request = read_json(request_path)
    validate_record("publication-request", request)
    _validate_request_identity(publication_directory, publication, request, adapter)
    attempts_directory = publication_directory / "attempts"
    for attempt_directory in attempts_directory.iterdir():
        if not attempt_directory.is_dir():
            continue
        attempt_request = attempt_directory / "request.json"
        if attempt_request.exists() and attempt_request.read_bytes() != request_bytes:
            raise WorkflowError("Publication attempt request differs from fixed request")
    prepared = _attempt_marker_exists(
        attempts_directory, "prepared.json", "prepared", request_bytes
    )
    send_started = _attempt_marker_exists(
        attempts_directory, "send-started.json", "send_started", request_bytes
    )
    return (
        request,
        request_bytes,
        bool(prepared and not send_started),
    )


def _attempt_marker_exists(
    attempts_directory: Path,
    filename: str,
    expected_phase: str,
    request_bytes: bytes,
) -> bool:
    found = False
    expected_hash = hashlib.sha256(request_bytes).hexdigest()
    for attempt_directory in attempts_directory.iterdir():
        if not attempt_directory.is_dir():
            continue
        marker_path = attempt_directory / filename
        if not marker_path.exists():
            continue
        marker = read_json(marker_path)
        validate_record("publication-attempt-marker", marker)
        if (
            marker["phase"] != expected_phase
            or marker["request_sha256"] != expected_hash
        ):
            raise WorkflowError("Publication attempt marker failed integrity validation")
        found = True
    return found


def _write_error(directory: Path, error: PublicationError) -> None:
    write_immutable_bytes(
        directory / "error.json",
        _json_bytes(
            {
                "kind": error.blocker_kind.value,
                "error_code": error.code,
                "message": str(error),
            }
        ),
    )


def _write_raw_error_response(directory: Path, error: PublicationError) -> None:
    if error.raw_response is None:
        return
    write_immutable_bytes(
        directory / "response-raw.json", _json_bytes(error.raw_response)
    )


def _slug(publication_id: str) -> str:
    return publication_id.replace("_", "-")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
