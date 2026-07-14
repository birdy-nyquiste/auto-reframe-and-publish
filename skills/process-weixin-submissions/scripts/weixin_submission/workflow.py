from __future__ import annotations

from pathlib import Path
from typing import Any

from .fake_blog import FakeBlogAdapter
from .storage import VALIDATION_SCOPE, initialize_repository, new_id, utc_now, write_json, write_text
from .submission import (
    SCHEMA_VERSION,
    build_placeholder_rewrite,
    load_structured_source,
    parse_scripted_input,
    structured_source_record,
)


MISSING_CAPABILITIES = (
    "durable state machine and retries",
    "WeChat and Windows Computer Use",
    "approved rewrite policy",
    "real Blog API",
)


def run_scripted_submission(
    repository: Path, input_path: Path, fake_blog_directory: Path
) -> dict[str, object]:
    initialize_repository(repository)
    submission = parse_scripted_input(input_path)
    started_at = utc_now()
    run_id = new_id("run")
    task_id = new_id("task")
    run_directory = repository / "runs" / run_id
    task_directory = repository / "tasks" / task_id

    task_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "created_in_run": run_id,
        "created_at": started_at,
        "updated_at": started_at,
        "target_id": submission.target_id,
        "requirements": submission.requirements,
        "milestone": "task_record_created",
        "blocker": None,
        "delivery_mode": "fake",
        "external_draft": None,
    }
    run_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "operation": "run",
        "started_at": started_at,
        "completed_at": None,
        "status": "processing",
        "input_window": {
            "adapter": "scripted",
            "window_id": submission.window_id,
            "input_path": str(input_path.resolve()),
        },
        "created_task_ids": [task_id],
        "attempted_task_ids": [],
    }
    write_json(task_directory / "task.json", task_record)
    write_json(run_directory / "run.json", run_record)

    raw_submission = {
        "schema_version": SCHEMA_VERSION,
        "window_id": submission.window_id,
        "header_text": submission.header_text,
        "article": {
            "title": submission.title,
            "body": submission.body,
            "source_url": submission.source_url,
            "images": list(submission.images),
        },
    }
    write_json(task_directory / "raw" / "submission.json", raw_submission)
    source_path = task_directory / "sources" / "article.json"
    write_json(source_path, structured_source_record(submission))
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
        "idempotency_key": task_id,
        "target_id": submission.target_id,
        "title": source.title,
        "body_markdown": rewrite,
        "images": list(source.images),
        "adapter": "fake",
    }
    write_json(task_directory / "delivery" / "request.json", delivery_request)
    task_record["milestone"] = "rewrite_artifact_ready"
    task_record["updated_at"] = utc_now()
    run_record["attempted_task_ids"] = [task_id]
    write_json(task_directory / "task.json", task_record)
    write_json(run_directory / "run.json", run_record)

    delivery_response = FakeBlogAdapter(fake_blog_directory).create_draft(delivery_request)
    write_json(task_directory / "delivery" / "response.json", delivery_response)

    completed_at = utc_now()
    task_record["updated_at"] = completed_at
    task_record["milestone"] = "fake_draft_confirmed"
    task_record["external_draft"] = delivery_response
    run_record["completed_at"] = completed_at
    run_record["status"] = "completed"
    write_json(task_directory / "task.json", task_record)
    write_json(run_directory / "run.json", run_record)

    report_path = run_directory / "report.md"
    write_text(
        report_path,
        "\n".join(
            (
                f"# Run {run_id}",
                "",
                "- Status: completed",
                f"- Input window: {submission.window_id}",
                f"- Task: {task_id}",
                f"- Target: {submission.target_id}",
                f"- Fake Blog draft: {delivery_response['draft_id']}",
                f"- Preview: {delivery_response['preview_url']}",
                f"- Validation scope: {VALIDATION_SCOPE}",
                f"- Not validated: {', '.join(MISSING_CAPABILITIES)}",
                "",
            )
        ),
    )
    return {
        "status": "completed",
        "run_id": run_id,
        "task_ids": [task_id],
        "report_path": str(report_path.resolve()),
        "validation_scope": VALIDATION_SCOPE,
        "missing_capabilities": list(MISSING_CAPABILITIES),
    }

