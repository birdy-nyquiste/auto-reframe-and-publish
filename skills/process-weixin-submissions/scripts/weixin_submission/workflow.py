from __future__ import annotations

from pathlib import Path
from typing import Any

from .fake_blog import BlogAdapterError, FakeBlogAdapter
from .protocol import IntakeCandidate, parse_input_window
from .retry_policy import retry_budget
from .scripted_chat import capture_next_window, establish_baseline
from .state import append_task_event, commit_task_milestone, load_record, save_record
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
    build_placeholder_rewrite,
    load_structured_source,
    parse_submission_messages,
    structured_source_record,
)


MILESTONES = (
    "task_created",
    "raw_evidence_ready",
    "structured_source_ready",
    "rewrite_artifact_ready",
    "draft_delivery_confirmed",
)

MISSING_CAPABILITIES = (
    "production retry budgets based on operational evidence",
    "full WeChat text and static-image capture",
    "Windows Computer Use",
    "approved rewrite policy",
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
) -> dict[str, object]:
    metadata = load_record("repository", repository / "repository.json")
    intake = metadata.get("intake")
    if not isinstance(intake, dict) or not isinstance(intake.get("last_marker_id"), str):
        raise WorkflowError("Initialize the scripted chat before running intake")
    window = capture_next_window(chat_path, intake["last_marker_id"])
    intake["last_marker_id"] = window.current_marker_id
    metadata["intake"] = intake
    metadata["validation_scope"] = VALIDATION_SCOPE
    save_record("repository", repository / "repository.json", metadata)
    candidates = parse_input_window(window.messages, window.current_marker_id)
    result = _run_candidates(
        repository,
        candidates,
        {
            "adapter": "scripted_chat",
            "conversation": window.conversation,
            "previous_marker_id": window.previous_marker_id,
            "current_marker_id": window.current_marker_id,
        },
        fake_blog_directory,
        simulate_interruption_after,
    )
    result["marker_id"] = window.current_marker_id
    return result


def _run_candidates(
    repository: Path,
    candidates: list[IntakeCandidate],
    input_window: dict[str, object],
    fake_blog_directory: Path,
    simulate_interruption_after: str | None,
) -> dict[str, object]:
    started_at = utc_now()
    run_id = new_id("run")
    run_directory = repository / "runs" / run_id
    created_task_ids = [new_id("task") for _candidate in candidates]
    result_by_task: dict[str, dict[str, object]] = {}

    for task_id, candidate in zip(created_task_ids, candidates):
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
        task_directory = repository / "tasks" / task_id
        save_record("task", task_directory / "task.json", task_record)
        append_task_event(
            task_directory,
            task_id,
            run_id,
            "milestone_committed",
            milestone="task_created",
        )
        write_json(
            task_directory / "raw" / "intake.json",
            {
                "schema_version": SCHEMA_VERSION,
                "window_id": _input_window_id(input_window),
                "messages": list(candidate.raw_messages),
            },
        )
        if submission is None:
            result_by_task[task_id] = {
                "task_id": task_id,
                "status": "needs_input",
                "blocker_reason": candidate.blocker_reason,
            }

    run_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "operation": "run",
        "started_at": started_at,
        "completed_at": None,
        "status": "processing",
        "input_window": input_window,
        "created_task_ids": created_task_ids,
        "attempted_task_ids": [],
        "recovered_by_run": None,
    }
    save_record("run", run_directory / "run.json", run_record)
    recovered_run_ids = _recover_processing_runs(repository, run_id)

    try:
        if any(candidate.submission is not None for candidate in candidates):
            _maybe_interrupt(simulate_interruption_after, "task_created")

        blog = FakeBlogAdapter(fake_blog_directory)
        executable = _load_executable_tasks(repository)
        for task_id, task_record, submission in executable:
            run_record["attempted_task_ids"].append(task_id)
            save_record("run", run_directory / "run.json", run_record)
            delivery_response = _process_task(
                repository / "tasks" / task_id,
                task_record,
                submission,
                blog,
                run_id,
                simulate_interruption_after,
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
        save_record("run", run_directory / "run.json", run_record)
        write_text(
            run_directory / "report.md",
            _render_interrupted_report(run_record, str(error)),
        )
        raise

    run_record["completed_at"] = utc_now()
    run_record["status"] = "completed"
    save_record("run", run_directory / "run.json", run_record)
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


def _process_task(
    task_directory: Path,
    task_record: dict[str, Any],
    submission: Submission,
    blog: FakeBlogAdapter,
    run_id: str,
    simulate_interruption_after: str | None,
) -> dict[str, Any] | None:
    task_id = task_record["task_id"]

    if task_record["milestone"] == "task_created":
        _start_attempt(task_directory, task_id, run_id, "capture_raw_evidence")
        write_json(
            task_directory / "raw" / "submission.json",
            _raw_submission_record(submission),
        )
        commit_task_milestone(
            task_directory, task_record, "raw_evidence_ready", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "raw_evidence_ready")
        _finish_attempt(task_directory, task_id, run_id, "capture_raw_evidence")

    if task_record["milestone"] == "raw_evidence_ready":
        _start_attempt(task_directory, task_id, run_id, "build_structured_source")
        source_path = task_directory / "sources" / "article.json"
        write_json(source_path, structured_source_record(submission.source))
        load_structured_source(source_path)
        commit_task_milestone(
            task_directory, task_record, "structured_source_ready", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "structured_source_ready")
        _finish_attempt(task_directory, task_id, run_id, "build_structured_source")

    source = load_structured_source(task_directory / "sources" / "article.json")
    if task_record["milestone"] == "structured_source_ready":
        _start_attempt(task_directory, task_id, run_id, "generate_rewrite")
        rewrite = build_placeholder_rewrite(submission, source)
        rewrite_manifest = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "placeholder_rewrite",
            "title": source.title,
            "target_id": submission.target_id,
            "requirements_mode": "custom" if submission.requirements else "default",
            "source_url": source.source_url,
            "images": list(source.images),
        }
        write_text(task_directory / "rewrite" / "content.md", rewrite)
        write_json(task_directory / "rewrite" / "manifest.json", rewrite_manifest)
        commit_task_milestone(
            task_directory, task_record, "rewrite_artifact_ready", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "rewrite_artifact_ready")
        _finish_attempt(task_directory, task_id, run_id, "generate_rewrite")

    if task_record["milestone"] == "rewrite_artifact_ready":
        _start_attempt(task_directory, task_id, run_id, "deliver_draft")
        rewrite = (task_directory / "rewrite" / "content.md").read_text(
            encoding="utf-8"
        )
        delivery_request = {
            "schema_version": SCHEMA_VERSION,
            "idempotency_key": task_id,
            "target_id": submission.target_id,
            "title": source.title,
            "body_markdown": rewrite,
            "images": list(source.images),
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
        previous_blocker = task_record["blocker"]
        task_record["blocker"] = None
        task_record["external_draft"] = delivery_response
        commit_task_milestone(
            task_directory, task_record, "draft_delivery_confirmed", run_id
        )
        _maybe_interrupt(simulate_interruption_after, "draft_delivery_confirmed")
        _finish_attempt(task_directory, task_id, run_id, "deliver_draft")
        if previous_blocker is not None:
            append_task_event(
                task_directory,
                task_id,
                run_id,
                "blocker_changed",
                details={"from": previous_blocker, "to": None},
            )

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
    task_id = task_record["task_id"]
    append_task_event(
        task_directory,
        task_id,
        run_id,
        "attempt_failed",
        operation="deliver_draft",
        outcome="failed",
        details={"error_category": error.category, "error_code": error.code},
    )
    budget = retry_budget("deliver_draft", error.category)
    previous_blocker = task_record["blocker"]
    if (
        isinstance(previous_blocker, dict)
        and previous_blocker.get("kind") == "retry_pending"
        and previous_blocker.get("retry_generation") == task_record["retry_generation"]
    ):
        attempts_used = int(previous_blocker["attempts_used"]) + 1
    else:
        attempts_used = 1

    if budget is None:
        blocker: dict[str, Any] = {
            "kind": "permanent_failure",
            "operation": "deliver_draft",
            "error_category": error.category,
            "error_code": error.code,
            "message": str(error),
        }
    else:
        blocker = {
            "kind": "retry_pending" if attempts_used < budget else "retry_exhausted",
            "operation": "deliver_draft",
            "error_category": error.category,
            "error_code": error.code,
            "attempts_used": attempts_used,
            "retry_budget": budget,
            "retry_generation": task_record["retry_generation"],
        }
    task_record["blocker"] = blocker
    task_record["updated_at"] = utc_now()
    save_record("task", task_directory / "task.json", task_record)
    append_task_event(
        task_directory,
        task_id,
        run_id,
        "blocker_changed",
        details={"from": previous_blocker, "to": blocker},
    )


def enable_retry(repository: Path, task_id: str) -> dict[str, object]:
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
    save_record("task", task_directory / "task.json", task_record)
    append_task_event(
        task_directory,
        task_id,
        run_id,
        "retry_enabled",
        operation=str(blocker["operation"]),
        outcome="enabled",
        details={"retry_generation": task_record["retry_generation"]},
    )
    append_task_event(
        task_directory,
        task_id,
        run_id,
        "blocker_changed",
        details={"from": blocker, "to": next_blocker},
    )
    run_record["completed_at"] = utc_now()
    run_record["status"] = "completed"
    save_record("run", run_directory / "run.json", run_record)
    write_text(
        run_directory / "report.md",
        f"# Run {run_id}\n\n- Status: completed\n- Retry enabled: {task_id}\n",
    )
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


def _raw_submission_record(submission: Submission) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "window_id": submission.window_id,
        "header_text": submission.header_text,
        "article": {
            "title": submission.source.title,
            "body": submission.source.body,
            "source_url": submission.source.source_url,
            "images": list(submission.source.images),
        },
    }


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
        save_record("run", run_path, run_record)
        write_text(
            run_directory / "report.md",
            _render_recovered_report(run_record),
        )
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
