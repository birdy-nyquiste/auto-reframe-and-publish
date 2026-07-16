from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .capture import (
    CaptureRejected,
    capture_raw_evidence,
    load_structured_source,
    rebuild_structured_source,
)
from .fake_blog import BlogAdapterError, FakeBlogAdapter
from .protocol import IntakeCandidate, parse_input_window
from .retry_policy import retry_budget
from .rewrite import (
    RewriteRejected,
    ScriptedRewriteOutcome,
    generate_validated_rewrite,
    load_rewrite_artifact,
)
from .schema_validation import SchemaValidationError
from .scripted_chat import capture_next_window, establish_baseline
from .state import (
    append_task_event,
    commit_task_milestone,
    commit_task_state,
    load_record,
    reconcile_task_projections,
    save_record,
)
from .storage import (
    VALIDATION_SCOPE,
    WorkflowError,
    initialize_repository,
    new_id,
    read_json,
    utc_now,
    write_json,
    write_text,
)
from .submission import (
    SCHEMA_VERSION,
    Submission,
    parse_submission_messages,
)


MISSING_CAPABILITIES = (
    "v1 tracer repository migration",
    "production retry budgets based on operational evidence",
    "real WeChat UI text and static-image capture adapter",
    "Windows Computer Use",
    "approved rewrite policy",
    "real Agent rewrite generation",
    "real Blog API",
)


class SimulatedInterruption(WorkflowError):
    """Validation-only interruption injected after a committed milestone."""


def initialize_scripted_chat(repository: Path, chat_path: Path) -> dict[str, object]:
    metadata = initialize_repository(repository)
    existing_intake = metadata.get("intake")
    if isinstance(existing_intake, dict) and isinstance(
        existing_intake.get("last_marker_id"), str
    ):
        raise WorkflowError(
            "Scripted intake is already initialized; run the next window instead"
        )
    marker_id, conversation = establish_baseline(chat_path)
    metadata["intake"] = {
        "adapter": "scripted_chat",
        "conversation": conversation,
        "last_marker_id": marker_id,
    }
    metadata["validation_scope"] = VALIDATION_SCOPE
    save_record("repository", repository / "repository.json", metadata)
    return {
        "status": "initialized",
        "repository": str(repository.resolve()),
        "baseline_marker_id": marker_id,
        "validation_scope": VALIDATION_SCOPE,
    }


def run_scripted_chat(
    repository: Path,
    chat_path: Path,
    fake_blog_directory: Path,
    simulate_interruption_after: str | None = None,
    scripted_rewrite_outcome: ScriptedRewriteOutcome = ScriptedRewriteOutcome.SUCCESS,
) -> dict[str, object]:
    metadata = load_record("repository", repository / "repository.json")
    intake = metadata.get("intake")
    if not isinstance(intake, dict) or not isinstance(intake.get("last_marker_id"), str):
        raise WorkflowError("Initialize the scripted chat before running intake")
    pending_window = metadata.get("pending_window")
    if pending_window is None:
        window = capture_next_window(chat_path, intake["last_marker_id"])
        candidates = parse_input_window(window.messages, window.current_marker_id)
        pending_window = {
            "adapter": "scripted_chat",
            "conversation": window.conversation,
            "previous_marker_id": window.previous_marker_id,
            "current_marker_id": window.current_marker_id,
            "messages": list(window.messages),
            "run_id": new_id("run"),
            "task_ids": [new_id("task") for _candidate in candidates],
        }
        metadata["pending_window"] = pending_window
        metadata["validation_scope"] = VALIDATION_SCOPE
        save_record("repository", repository / "repository.json", metadata)
    if not isinstance(pending_window, dict):
        raise WorkflowError("Repository pending_window is invalid")
    current_marker_id = str(pending_window["current_marker_id"])
    messages = pending_window["messages"]
    candidates = parse_input_window(messages, current_marker_id)
    task_ids = pending_window["task_ids"]
    if not isinstance(task_ids, list) or len(task_ids) != len(candidates):
        raise WorkflowError("Pending input window task IDs do not match its candidates")

    def commit_input_cursor() -> None:
        intake["last_marker_id"] = current_marker_id
        metadata["intake"] = intake
        metadata["pending_window"] = None
        metadata["validation_scope"] = VALIDATION_SCOPE
        save_record("repository", repository / "repository.json", metadata)

    result = _run_candidates(
        repository,
        candidates,
        pending_window,
        fake_blog_directory,
        simulate_interruption_after,
        scripted_rewrite_outcome,
        str(pending_window["run_id"]),
        [str(task_id) for task_id in task_ids],
        commit_input_cursor,
    )
    result["marker_id"] = current_marker_id
    return result


def _run_candidates(
    repository: Path,
    candidates: list[IntakeCandidate],
    input_window: dict[str, object],
    fake_blog_directory: Path,
    simulate_interruption_after: str | None,
    scripted_rewrite_outcome: ScriptedRewriteOutcome,
    run_id: str,
    created_task_ids: list[str],
    commit_input_cursor: Callable[[], None],
) -> dict[str, object]:
    run_directory = repository / "runs" / run_id
    result_by_task: dict[str, dict[str, object]] = {}
    run_path = run_directory / "run.json"
    if run_path.exists():
        run_record = load_record("run", run_path)
        if run_record["status"] != "processing":
            raise WorkflowError(f"Pending input run {run_id} is not processing")
        if run_record["created_task_ids"] != created_task_ids:
            raise WorkflowError(f"Pending input run {run_id} has different task IDs")
    else:
        run_record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "operation": "run",
            "started_at": utc_now(),
            "completed_at": None,
            "status": "processing",
            "input_window": input_window,
            "created_task_ids": created_task_ids,
            "attempted_task_ids": [],
            "recovered_by_run": None,
        }
        save_record("run", run_path, run_record)
    started_at = str(run_record["started_at"])
    reconcile_task_projections(repository)
    recovered_run_ids = _recover_processing_runs(repository, run_id)

    for task_id, candidate in zip(created_task_ids, candidates):
        task_directory = repository / "tasks" / task_id
        task_path = task_directory / "task.json"
        if task_path.exists() or (task_directory / "events").exists():
            existing_task = load_record("task", task_path)
            if existing_task["created_in_run"] != run_id:
                raise WorkflowError(f"Task {task_id} belongs to another run")
            result_by_task[task_id] = _result_from_task(existing_task)
            continue
        submission = candidate.submission
        blocker = (
            None
            if candidate.blocker_reason is None
            else {
                "kind": "needs_input",
                "reason": candidate.blocker_reason,
                "message": candidate.blocker_message,
            }
        )
        task_record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "created_in_run": run_id,
            "created_at": started_at,
            "updated_at": started_at,
            "target_id": candidate.target_id,
            "requirements": submission.requirements if submission else None,
            "milestone": "task_created",
            "blocker": blocker,
            "delivery_mode": "fake" if submission else None,
            "external_draft": None,
            "retry_generation": 0,
        }
        raw_intake = {
            "schema_version": SCHEMA_VERSION,
            "window_id": _input_window_id(input_window),
            "messages": list(candidate.raw_messages),
        }
        commit_task_state(
            task_directory,
            task_record,
            run_id,
            "milestone_committed",
            milestone="task_created",
            details={"raw_intake": raw_intake},
        )
        write_json(task_directory / "raw" / "intake.json", raw_intake)
        if submission is None:
            result_by_task[task_id] = {
                "task_id": task_id,
                "status": "needs_input",
                "blocker_reason": candidate.blocker_reason,
            }

    commit_input_cursor()

    try:
        if any(candidate.submission is not None for candidate in candidates):
            _maybe_interrupt(simulate_interruption_after, "task_created")

        blog = FakeBlogAdapter(fake_blog_directory)
        executable = _load_executable_tasks(repository)
        for task_id, task_record, submission in executable:
            if task_id not in run_record["attempted_task_ids"]:
                run_record["attempted_task_ids"].append(task_id)
            save_record("run", run_directory / "run.json", run_record)
            delivery_response = _process_task(
                repository / "tasks" / task_id,
                task_record,
                submission,
                blog,
                run_id,
                simulate_interruption_after,
                scripted_rewrite_outcome,
            )
            if delivery_response is None:
                blocker = task_record["blocker"]
                if not isinstance(blocker, dict):
                    raise WorkflowError(f"Task {task_id} failed without a blocker")
                result_by_task[task_id] = {
                    "task_id": task_id,
                    "status": blocker["kind"],
                    "blocker_reason": blocker["error_code"],
                }
            else:
                result_by_task[task_id] = {
                    "task_id": task_id,
                    "status": "fake_draft_confirmed",
                    "draft_id": delivery_response["draft_id"],
                }
    except SimulatedInterruption as error:
        run_record["completed_at"] = utc_now()
        run_record["status"] = "interrupted"
        write_text(
            run_directory / "report.md",
            _render_interrupted_report(run_record, str(error)),
        )
        save_record("run", run_directory / "run.json", run_record)
        raise

    ordered_result_ids = created_task_ids + [
        task_id
        for task_id in run_record["attempted_task_ids"]
        if task_id not in created_task_ids
    ]
    task_results = [result_by_task[task_id] for task_id in ordered_result_ids]
    report_path = run_directory / "report.md"
    write_text(
        report_path,
        _render_report(run_id, input_window, task_results, recovered_run_ids),
    )
    run_record["completed_at"] = utc_now()
    run_record["status"] = "completed"
    save_record("run", run_directory / "run.json", run_record)
    return {
        "status": "completed",
        "run_id": run_id,
        "task_ids": created_task_ids,
        "attempted_task_ids": run_record["attempted_task_ids"],
        "task_results": task_results,
        "report_path": str(report_path.resolve()),
        "validation_scope": VALIDATION_SCOPE,
        "missing_capabilities": list(MISSING_CAPABILITIES),
    }


def _load_executable_tasks(
    repository: Path,
) -> list[tuple[str, dict[str, Any], Submission]]:
    executable: list[tuple[str, dict[str, Any], Submission]] = []
    task_directories = sorted(
        (path for path in (repository / "tasks").iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    for task_directory in task_directories:
        task_record = load_record("task", task_directory / "task.json")
        if task_record["milestone"] == "draft_delivery_confirmed":
            continue
        blocker = task_record["blocker"]
        if blocker is not None:
            if not isinstance(blocker, dict) or blocker.get("kind") != "retry_pending":
                continue
        intake = read_json(task_directory / "raw" / "intake.json")
        submission = parse_submission_messages(
            intake.get("messages"),
            str(intake.get("window_id", task_record["created_in_run"])),
        )
        executable.append((task_directory.name, task_record, submission))
    return executable


def _result_from_task(task_record: dict[str, Any]) -> dict[str, object]:
    external_draft = task_record["external_draft"]
    if isinstance(external_draft, dict):
        return {
            "task_id": str(task_record["task_id"]),
            "status": "fake_draft_confirmed",
            "draft_id": str(external_draft["draft_id"]),
        }
    blocker = task_record["blocker"]
    if isinstance(blocker, dict):
        reason = blocker.get("reason", blocker.get("error_code"))
        return {
            "task_id": str(task_record["task_id"]),
            "status": str(blocker["kind"]),
            "blocker_reason": str(reason),
        }
    return {"task_id": str(task_record["task_id"]), "status": "pending"}


def _process_task(
    task_directory: Path,
    task_record: dict[str, Any],
    submission: Submission,
    blog: FakeBlogAdapter,
    run_id: str,
    simulate_interruption_after: str | None,
    scripted_rewrite_outcome: ScriptedRewriteOutcome,
) -> dict[str, Any] | None:
    task_id = task_record["task_id"]

    if task_record["milestone"] == "task_created":
        _start_attempt(task_directory, task_id, run_id, "capture_raw_evidence")
        try:
            capture_raw_evidence(task_directory, submission, run_id)
        except CaptureRejected as error:
            _record_capture_failure(task_directory, task_record, run_id, error)
            return None
        except (SchemaValidationError, WorkflowError) as error:
            _record_operation_failure(
                task_directory,
                task_record,
                run_id,
                operation="capture_raw_evidence",
                error_category="invalid_capture",
                error_code="invalid_capture_evidence",
                message=str(error),
                retryable=False,
            )
            return None
        commit_task_milestone(
            task_directory, task_record, "raw_evidence_ready", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "raw_evidence_ready")
        _finish_attempt(task_directory, task_id, run_id, "capture_raw_evidence")

    if task_record["milestone"] == "raw_evidence_ready":
        _start_attempt(task_directory, task_id, run_id, "build_structured_source")
        try:
            rebuild_structured_source(task_directory)
        except (SchemaValidationError, WorkflowError) as error:
            _record_operation_failure(
                task_directory,
                task_record,
                run_id,
                operation="build_structured_source",
                error_category="evidence_integrity",
                error_code="evidence_integrity_failed",
                message=str(error),
                retryable=False,
            )
            return None
        commit_task_milestone(
            task_directory, task_record, "structured_source_ready", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "structured_source_ready")
        _finish_attempt(task_directory, task_id, run_id, "build_structured_source")

    if task_record["milestone"] == "structured_source_ready":
        _start_attempt(task_directory, task_id, run_id, "generate_rewrite")
        try:
            source = load_structured_source(
                task_directory / "sources" / "article.json"
            )
            generate_validated_rewrite(
                task_directory,
                submission,
                source,
                run_id,
                scripted_rewrite_outcome,
            )
        except RewriteRejected as error:
            _record_operation_failure(
                task_directory,
                task_record,
                run_id,
                operation="generate_rewrite",
                error_category=error.category,
                error_code=error.code,
                message=str(error),
                retryable=False,
            )
            return None
        except (SchemaValidationError, WorkflowError) as error:
            _record_operation_failure(
                task_directory,
                task_record,
                run_id,
                operation="generate_rewrite",
                error_category="rewrite_validation",
                error_code="rewrite_generation_invalid",
                message=str(error),
                retryable=False,
            )
            return None
        commit_task_milestone(
            task_directory, task_record, "rewrite_artifact_ready", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "rewrite_artifact_ready")
        _finish_attempt(task_directory, task_id, run_id, "generate_rewrite")

    if task_record["milestone"] == "rewrite_artifact_ready":
        _start_attempt(
            task_directory, task_id, run_id, "validate_rewrite_artifact"
        )
        try:
            artifact = load_rewrite_artifact(
                task_directory, submission.target_id, submission.requirements
            )
        except (SchemaValidationError, WorkflowError) as error:
            _record_operation_failure(
                task_directory,
                task_record,
                run_id,
                operation="validate_rewrite_artifact",
                error_category="rewrite_integrity",
                error_code="rewrite_artifact_invalid",
                message=str(error),
                retryable=False,
            )
            return None
        _finish_attempt(
            task_directory, task_id, run_id, "validate_rewrite_artifact"
        )
        _start_attempt(task_directory, task_id, run_id, "deliver_draft")
        delivery_request = {
            "schema_version": SCHEMA_VERSION,
            "idempotency_key": task_id,
            "target_id": artifact.target_id,
            "title": artifact.title,
            "body_markdown": artifact.content,
            "images": list(artifact.images),
            "adapter": "fake",
        }
        write_json(task_directory / "delivery" / "request.json", delivery_request)
        try:
            delivery_response = blog.create_draft(delivery_request)
        except BlogAdapterError as error:
            _record_delivery_failure(
                task_directory, task_record, run_id, error
            )
            return None
        write_json(task_directory / "delivery" / "response.json", delivery_response)
        task_record["blocker"] = None
        task_record["external_draft"] = delivery_response
        commit_task_milestone(
            task_directory, task_record, "draft_delivery_confirmed", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "draft_delivery_confirmed")
        _finish_attempt(task_directory, task_id, run_id, "deliver_draft")

    external_draft = task_record["external_draft"]
    if not isinstance(external_draft, dict):
        raise WorkflowError(f"Task {task_id} has no confirmed draft response")
    return external_draft


def _record_delivery_failure(
    task_directory: Path,
    task_record: dict[str, Any],
    run_id: str,
    error: BlogAdapterError,
) -> None:
    _record_operation_failure(
        task_directory,
        task_record,
        run_id,
        operation="deliver_draft",
        error_category=error.category,
        error_code=error.code,
        message=str(error),
        retryable=True,
    )


def _record_capture_failure(
    task_directory: Path,
    task_record: dict[str, Any],
    run_id: str,
    error: CaptureRejected,
) -> None:
    _record_operation_failure(
        task_directory,
        task_record,
        run_id,
        operation="capture_raw_evidence",
        error_category=error.category,
        error_code=error.code,
        message=str(error),
        retryable=error.retryable,
    )


def _record_operation_failure(
    task_directory: Path,
    task_record: dict[str, Any],
    run_id: str,
    *,
    operation: str,
    error_category: str,
    error_code: str,
    message: str,
    retryable: bool,
) -> None:
    previous_blocker = task_record["blocker"]
    budget = retry_budget(operation, error_category) if retryable else None
    if budget is not None:
        if (
            isinstance(previous_blocker, dict)
            and previous_blocker.get("kind") == "retry_pending"
            and previous_blocker.get("retry_generation")
            == task_record["retry_generation"]
        ):
            attempts_used = int(previous_blocker["attempts_used"]) + 1
        else:
            attempts_used = 1
        blocker: dict[str, Any] = {
            "kind": "retry_pending" if attempts_used < budget else "retry_exhausted",
            "operation": operation,
            "error_category": error_category,
            "error_code": error_code,
            "attempts_used": attempts_used,
            "retry_budget": budget,
            "retry_generation": task_record["retry_generation"],
        }
    else:
        blocker = {
            "kind": "permanent_failure",
            "operation": operation,
            "error_category": error_category,
            "error_code": error_code,
            "message": message,
        }
    task_record["blocker"] = blocker
    task_record["updated_at"] = utc_now()
    commit_task_state(
        task_directory,
        task_record,
        run_id,
        "attempt_failed",
        operation=operation,
        outcome="failed",
        details={
            "error_category": error_category,
            "error_code": error_code,
            "blocker_from": previous_blocker,
            "blocker_to": blocker,
        },
    )


def enable_retry(repository: Path, task_id: str) -> dict[str, object]:
    metadata = load_record("repository", repository / "repository.json")
    if metadata["pending_window"] is not None:
        raise WorkflowError("Complete the pending input window before retrying a task")
    task_directory = repository / "tasks" / task_id
    task_record = load_record("task", task_directory / "task.json")
    blocker = task_record["blocker"]
    if not isinstance(blocker, dict) or blocker.get("kind") != "retry_exhausted":
        raise WorkflowError(f"Task {task_id} is not retry_exhausted")

    started_at = utc_now()
    run_id = new_id("run")
    run_directory = repository / "runs" / run_id
    run_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "operation": "retry",
        "started_at": started_at,
        "completed_at": None,
        "status": "processing",
        "input_window": {"task_id": task_id},
        "created_task_ids": [],
        "attempted_task_ids": [],
        "recovered_by_run": None,
    }
    save_record("run", run_directory / "run.json", run_record)
    reconcile_task_projections(repository)
    _recover_processing_runs(repository, run_id)

    task_record["retry_generation"] += 1
    next_blocker = {
        "kind": "retry_pending",
        "operation": blocker["operation"],
        "error_category": blocker["error_category"],
        "error_code": blocker["error_code"],
        "attempts_used": 0,
        "retry_budget": blocker["retry_budget"],
        "retry_generation": task_record["retry_generation"],
    }
    task_record["blocker"] = next_blocker
    task_record["updated_at"] = utc_now()
    commit_task_state(
        task_directory,
        task_record,
        run_id,
        "retry_enabled",
        operation=str(blocker["operation"]),
        outcome="enabled",
        details={
            "retry_generation": task_record["retry_generation"],
            "blocker_from": blocker,
            "blocker_to": next_blocker,
        },
    )
    write_text(
        run_directory / "report.md",
        f"# Run {run_id}\n\n- Status: completed\n- Retry enabled: {task_id}\n",
    )
    run_record["completed_at"] = utc_now()
    run_record["status"] = "completed"
    save_record("run", run_directory / "run.json", run_record)
    return {
        "status": "retry_enabled",
        "run_id": run_id,
        "task_id": task_id,
        "retry_generation": task_record["retry_generation"],
    }


def _start_attempt(
    task_directory: Path, task_id: str, run_id: str, operation: str
) -> None:
    append_task_event(
        task_directory,
        task_id,
        run_id,
        "attempt_started",
        operation=operation,
        outcome="started",
    )


def _finish_attempt(
    task_directory: Path, task_id: str, run_id: str, operation: str
) -> None:
    append_task_event(
        task_directory,
        task_id,
        run_id,
        "attempt_succeeded",
        operation=operation,
        outcome="succeeded",
    )


def _maybe_interrupt(requested: str | None, milestone: str) -> None:
    if requested == milestone:
        raise SimulatedInterruption(
            f"Simulated interruption after committed milestone {milestone}"
        )


def _input_window_id(input_window: dict[str, object]) -> str:
    value = input_window.get("current_marker_id") or input_window.get("window_id")
    return str(value)


def _render_report(
    run_id: str,
    input_window: dict[str, object],
    task_results: list[dict[str, object]],
    recovered_run_ids: list[str],
) -> str:
    lines = [
        f"# Run {run_id}",
        "",
        "- Status: completed",
        f"- Input window: {input_window}",
        f"- Tasks: {len(task_results)}",
        f"- Recovered runs: {', '.join(recovered_run_ids) if recovered_run_ids else 'none'}",
        f"- Validation scope: {VALIDATION_SCOPE}",
        f"- Not validated: {', '.join(MISSING_CAPABILITIES)}",
        "",
        "## Task results",
        "",
    ]
    for result in task_results:
        line = f"- {result['task_id']}: {result['status']}"
        if result.get("draft_id"):
            line += f" ({result['draft_id']})"
        if result.get("blocker_reason"):
            line += f" ({result['blocker_reason']})"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def _recover_processing_runs(repository: Path, current_run_id: str) -> list[str]:
    recovered: list[str] = []
    for run_directory in sorted((repository / "runs").iterdir()):
        if not run_directory.is_dir() or run_directory.name == current_run_id:
            continue
        run_path = run_directory / "run.json"
        run_record = load_record("run", run_path)
        if run_record["status"] != "processing":
            continue
        run_record["status"] = "interrupted"
        run_record["completed_at"] = utc_now()
        run_record["recovered_by_run"] = current_run_id
        write_text(
            run_directory / "report.md",
            _render_recovered_report(run_record),
        )
        save_record("run", run_path, run_record)
        recovered.append(str(run_record["run_id"]))
    return recovered


def _render_interrupted_report(run_record: dict[str, Any], reason: str) -> str:
    return "\n".join(
        [
            f"# Run {run_record['run_id']}",
            "",
            "- Status: interrupted",
            f"- Reason: {reason}",
            f"- Created tasks: {', '.join(run_record['created_task_ids']) or 'none'}",
            f"- Attempted tasks: {', '.join(run_record['attempted_task_ids']) or 'none'}",
            "",
        ]
    )


def _render_recovered_report(run_record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Run {run_record['run_id']}",
            "",
            "- Status: interrupted",
            "- Reason: previous process ended without recording completion",
            f"- Recovered by run: {run_record['recovered_by_run']}",
            f"- Created tasks: {', '.join(run_record['created_task_ids']) or 'none'}",
            f"- Attempted tasks: {', '.join(run_record['attempted_task_ids']) or 'none'}",
            "",
        ]
    )
