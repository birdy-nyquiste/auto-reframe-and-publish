from __future__ import annotations

from pathlib import Path
from typing import Any

from .fake_blog import FakeBlogAdapter
from .protocol import IntakeCandidate, parse_input_window
from .scripted_chat import capture_next_window, establish_baseline
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
    structured_source_record,
)


MISSING_CAPABILITIES = (
    "JSON Schema and transition validation",
    "writer locking, event history, and crash recovery",
    "durable retries",
    "full WeChat text and static-image capture",
    "Windows Computer Use",
    "approved rewrite policy",
    "real Blog API",
)


def initialize_scripted_chat(repository: Path, chat_path: Path) -> dict[str, object]:
    metadata = initialize_repository(repository)
    marker_id, conversation = establish_baseline(chat_path)
    metadata["intake"] = {
        "adapter": "scripted_chat",
        "conversation": conversation,
        "last_marker_id": marker_id,
    }
    metadata["validation_scope"] = VALIDATION_SCOPE
    write_json(repository / "repository.json", metadata)
    return {
        "status": "initialized",
        "repository": str(repository.resolve()),
        "baseline_marker_id": marker_id,
        "validation_scope": VALIDATION_SCOPE,
    }


def run_scripted_chat(
    repository: Path, chat_path: Path, fake_blog_directory: Path
) -> dict[str, object]:
    metadata = read_json(repository / "repository.json")
    intake = metadata.get("intake")
    if not isinstance(intake, dict) or not isinstance(intake.get("last_marker_id"), str):
        raise WorkflowError("Initialize the scripted chat before running intake")
    window = capture_next_window(chat_path, intake["last_marker_id"])
    intake["last_marker_id"] = window.current_marker_id
    metadata["intake"] = intake
    metadata["validation_scope"] = VALIDATION_SCOPE
    write_json(repository / "repository.json", metadata)
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
    )
    result["marker_id"] = window.current_marker_id
    return result


def _run_candidates(
    repository: Path,
    candidates: list[IntakeCandidate],
    input_window: dict[str, object],
    fake_blog_directory: Path,
) -> dict[str, object]:
    started_at = utc_now()
    run_id = new_id("run")
    run_directory = repository / "runs" / run_id
    task_ids = [new_id("task") for _candidate in candidates]
    task_records: dict[str, dict[str, Any]] = {}
    task_results: list[dict[str, object]] = []

    for task_id, candidate in zip(task_ids, candidates):
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
            "milestone": "task_record_created",
            "blocker": blocker,
            "delivery_mode": "fake" if submission else None,
            "external_draft": None,
        }
        task_records[task_id] = task_record
        task_directory = repository / "tasks" / task_id
        write_json(task_directory / "task.json", task_record)
        write_json(
            task_directory / "raw" / "intake.json",
            {
                "schema_version": SCHEMA_VERSION,
                "messages": list(candidate.raw_messages),
            },
        )
        if submission is not None:
            write_json(
                task_directory / "raw" / "submission.json",
                _raw_submission_record(submission),
            )

    run_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "operation": "run",
        "started_at": started_at,
        "completed_at": None,
        "status": "processing",
        "input_window": input_window,
        "created_task_ids": task_ids,
        "attempted_task_ids": [],
    }
    write_json(run_directory / "run.json", run_record)

    blog = FakeBlogAdapter(fake_blog_directory)
    for task_id, candidate in zip(task_ids, candidates):
        if candidate.submission is None:
            task_results.append(
                {
                    "task_id": task_id,
                    "status": "needs_input",
                    "blocker_reason": candidate.blocker_reason,
                }
            )
            continue
        run_record["attempted_task_ids"].append(task_id)
        write_json(run_directory / "run.json", run_record)
        delivery_response = _process_valid_submission(
            repository / "tasks" / task_id,
            task_records[task_id],
            candidate.submission,
            blog,
        )
        task_results.append(
            {
                "task_id": task_id,
                "status": "fake_draft_confirmed",
                "draft_id": delivery_response["draft_id"],
            }
        )

    completed_at = utc_now()
    run_record["completed_at"] = completed_at
    run_record["status"] = "completed"
    write_json(run_directory / "run.json", run_record)
    report_path = run_directory / "report.md"
    write_text(
        report_path,
        _render_report(run_id, input_window, task_results),
    )
    return {
        "status": "completed",
        "run_id": run_id,
        "task_ids": task_ids,
        "task_results": task_results,
        "report_path": str(report_path.resolve()),
        "validation_scope": VALIDATION_SCOPE,
        "missing_capabilities": list(MISSING_CAPABILITIES),
    }


def _process_valid_submission(
    task_directory: Path,
    task_record: dict[str, Any],
    submission: Submission,
    blog: FakeBlogAdapter,
) -> dict[str, Any]:
    source_path = task_directory / "sources" / "article.json"
    write_json(source_path, structured_source_record(submission.source))
    source = load_structured_source(source_path)
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

    delivery_request = {
        "schema_version": SCHEMA_VERSION,
        "idempotency_key": task_record["task_id"],
        "target_id": submission.target_id,
        "title": source.title,
        "body_markdown": rewrite,
        "images": list(source.images),
        "adapter": "fake",
    }
    write_json(task_directory / "delivery" / "request.json", delivery_request)
    task_record["milestone"] = "rewrite_artifact_ready"
    task_record["updated_at"] = utc_now()
    write_json(task_directory / "task.json", task_record)

    delivery_response = blog.create_draft(delivery_request)
    write_json(task_directory / "delivery" / "response.json", delivery_response)
    task_record["updated_at"] = utc_now()
    task_record["milestone"] = "fake_draft_confirmed"
    task_record["external_draft"] = delivery_response
    write_json(task_directory / "task.json", task_record)
    return delivery_response


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
) -> str:
    lines = [
        f"# Run {run_id}",
        "",
        "- Status: completed",
        f"- Input window: {input_window}",
        f"- Tasks: {len(task_results)}",
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
