#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = 1
REPOSITORY_VERSION = 1


class WorkflowError(Exception):
    """An operator-facing validation or workflow error."""


@dataclass(frozen=True)
class Submission:
    window_id: str
    header_text: str
    target_id: str
    requirements: str | None
    title: str
    body: str
    source_url: str | None
    images: tuple[str, ...]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


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


def require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{field} must be a non-empty string")
    return value


def parse_task_header(text: str) -> tuple[str, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "#投稿":
        raise WorkflowError("Task header must start with #投稿")

    target_id: str | None = None
    requirements: str | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("目标:"):
            target_id = line.removeprefix("目标:").strip()
            continue
        if line.startswith("要求:"):
            first_line = line.removeprefix("要求:").strip()
            remainder = "\n".join(lines[index + 1 :]).strip()
            requirements = "\n".join(part for part in (first_line, remainder) if part) or None
            break

    if not target_id:
        raise WorkflowError("Task header is missing a non-empty target")
    return target_id, requirements


def parse_scripted_input(path: Path) -> Submission:
    payload = read_json(path)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise WorkflowError(f"scripted input schema_version must be {SCHEMA_VERSION}")
    window_id = require_string(payload.get("window_id"), "window_id")
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise WorkflowError("Ticket 01 scripted input must contain exactly two messages")
    header, article = messages
    if not isinstance(header, dict) or header.get("kind") != "task_header":
        raise WorkflowError("The first message must be a task_header")
    if not isinstance(article, dict) or article.get("kind") != "official_account_article":
        raise WorkflowError("The second message must be an official_account_article")

    header_text = require_string(header.get("text"), "task header text")
    target_id, requirements = parse_task_header(header_text)
    title = require_string(article.get("title"), "article title")
    body = require_string(article.get("body"), "article body")
    source_url_value = article.get("source_url")
    if source_url_value is not None and not isinstance(source_url_value, str):
        raise WorkflowError("source_url must be a string or null")
    images_value = article.get("images", [])
    if not isinstance(images_value, list) or not all(
        isinstance(item, str) for item in images_value
    ):
        raise WorkflowError("images must be a list of strings")

    return Submission(
        window_id=window_id,
        header_text=header_text,
        target_id=target_id,
        requirements=requirements,
        title=title,
        body=body,
        source_url=source_url_value,
        images=tuple(images_value),
    )


def initialize_repository(repository: Path) -> dict[str, Any]:
    repository.mkdir(parents=True, exist_ok=True)
    (repository / "runs").mkdir(exist_ok=True)
    (repository / "tasks").mkdir(exist_ok=True)
    metadata_path = repository / "repository.json"
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        if metadata.get("repository_version") != REPOSITORY_VERSION:
            raise WorkflowError("Unsupported repository version")
        return metadata

    metadata = {
        "repository_version": REPOSITORY_VERSION,
        "created_at": utc_now(),
        "readiness": "development",
    }
    write_json(metadata_path, metadata)
    return metadata


def build_placeholder_rewrite(submission: Submission) -> str:
    requirement_note = submission.requirements or "默认改写规则（Ticket 09 前为占位）"
    return (
        f"# {submission.title}\n\n"
        "> 这是 Ticket 01 的可验证替代改写产物，不代表正式内容改写规则。\n\n"
        f"## 编辑要求\n\n{requirement_note}\n\n"
        f"## 正文\n\n{submission.body}\n"
    )


class FakeBlogAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def create_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        drafts = self.directory / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        existing = sorted(drafts.glob("draft-*.json"))
        draft_id = f"draft-{len(existing) + 1:06d}"
        response = {
            "draft_id": draft_id,
            "status": "accepted",
            "preview_url": f"https://blog.example.test/drafts/{draft_id}",
        }
        write_json(drafts / f"{draft_id}.json", {"request": request, "response": response})
        return response


def run_scripted_submission(
    repository: Path, input_path: Path, fake_blog_directory: Path
) -> dict[str, Any]:
    initialize_repository(repository)
    submission = parse_scripted_input(input_path)
    started_at = utc_now()
    run_id = new_id("run")
    task_id = new_id("task")
    run_directory = repository / "runs" / run_id
    task_directory = repository / "tasks" / task_id

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

    rewrite = build_placeholder_rewrite(submission)
    rewrite_manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "placeholder_rewrite",
        "title": submission.title,
        "target_id": submission.target_id,
        "requirements_mode": "custom" if submission.requirements else "default",
        "source_url": submission.source_url,
        "images": list(submission.images),
    }
    write_text(task_directory / "rewrite" / "content.md", rewrite)
    write_json(task_directory / "rewrite" / "manifest.json", rewrite_manifest)

    delivery_request = {
        "schema_version": SCHEMA_VERSION,
        "idempotency_key": task_id,
        "target_id": submission.target_id,
        "title": submission.title,
        "body_markdown": rewrite,
        "images": list(submission.images),
    }
    write_json(task_directory / "delivery" / "request.json", delivery_request)
    delivery_response = FakeBlogAdapter(fake_blog_directory).create_draft(delivery_request)
    write_json(task_directory / "delivery" / "response.json", delivery_response)

    completed_at = utc_now()
    task_record = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "created_in_run": run_id,
        "created_at": started_at,
        "updated_at": completed_at,
        "target_id": submission.target_id,
        "requirements": submission.requirements,
        "milestone": "external_draft_confirmed",
        "blocker": None,
        "external_draft": delivery_response,
    }
    run_record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "operation": "run",
        "started_at": started_at,
        "completed_at": completed_at,
        "status": "completed",
        "input_window": {
            "adapter": "scripted",
            "window_id": submission.window_id,
            "input_path": str(input_path.resolve()),
        },
        "created_task_ids": [task_id],
        "attempted_task_ids": [task_id],
    }
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
                "- Readiness: development (Ticket 01 tracer only)",
                "",
            )
        ),
    )
    return {
        "status": "completed",
        "run_id": run_id,
        "task_ids": [task_id],
        "report_path": str(report_path.resolve()),
        "readiness": "development",
    }


def repository_status(repository: Path) -> dict[str, Any]:
    metadata = read_json(repository / "repository.json")
    run_count = sum(1 for path in (repository / "runs").iterdir() if path.is_dir())
    task_count = sum(1 for path in (repository / "tasks").iterdir() if path.is_dir())
    return {
        "status": "ok",
        "repository_version": metadata["repository_version"],
        "readiness": metadata["readiness"],
        "run_count": run_count,
        "task_count": task_count,
    }


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process manually triggered WeChat submissions."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    initialize = subparsers.add_parser("initialize", help="Initialize a task repository.")
    initialize.add_argument("--repository", type=Path, required=True)

    run = subparsers.add_parser("run", help="Run the Ticket 01 scripted tracer.")
    run.add_argument("--repository", type=Path, required=True)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--blog-adapter", choices=("fake",), required=True)
    run.add_argument("--fake-blog-directory", type=Path, required=True)

    status = subparsers.add_parser("status", help="Read task repository status.")
    status.add_argument("--repository", type=Path, required=True)

    retry = subparsers.add_parser(
        "retry", help="Retry a task after durable retry support is implemented."
    )
    retry.add_argument("--repository", type=Path, required=True)
    retry.add_argument("--task-id", required=True)
    return parser


def execute(arguments: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if arguments.operation == "initialize":
        metadata = initialize_repository(arguments.repository)
        return 0, {
            "status": "initialized",
            "repository": str(arguments.repository.resolve()),
            **metadata,
        }
    if arguments.operation == "run":
        return 0, run_scripted_submission(
            arguments.repository, arguments.input, arguments.fake_blog_directory
        )
    if arguments.operation == "status":
        return 0, repository_status(arguments.repository)
    if arguments.operation == "retry":
        return 3, {
            "status": "not_available",
            "operation": "retry",
            "task_id": arguments.task_id,
            "reason": "Durable retry is implemented by Ticket 03.",
        }
    raise WorkflowError(f"Unsupported operation: {arguments.operation}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    try:
        exit_code, result = execute(arguments)
    except WorkflowError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

