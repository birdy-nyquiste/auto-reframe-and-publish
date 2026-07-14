from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .storage import WorkflowError, read_json


SCHEMA_VERSION = 1


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


@dataclass(frozen=True)
class StructuredSource:
    title: str
    body: str
    source_url: str | None
    images: tuple[str, ...]


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


def structured_source_record(submission: Submission) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "title": submission.title,
        "body": submission.body,
        "source_url": submission.source_url,
        "images": list(submission.images),
    }


def load_structured_source(path: Path) -> StructuredSource:
    record = read_json(path)
    title = require_string(record.get("title"), "structured source title")
    body = require_string(record.get("body"), "structured source body")
    source_url = record.get("source_url")
    if source_url is not None and not isinstance(source_url, str):
        raise WorkflowError("structured source URL must be a string or null")
    images = record.get("images")
    if not isinstance(images, list) or not all(isinstance(item, str) for item in images):
        raise WorkflowError("structured source images must be a list of strings")
    return StructuredSource(title, body, source_url, tuple(images))


def build_placeholder_rewrite(
    submission: Submission, source: StructuredSource
) -> str:
    requirement_note = submission.requirements or "默认改写规则（Ticket 09 前为占位）"
    return (
        f"# {source.title}\n\n"
        "> 这是 Ticket 01 的可验证替代改写产物，不代表正式内容改写规则。\n\n"
        f"## 编辑要求\n\n{requirement_note}\n\n"
        f"## 正文\n\n{source.body}\n"
    )

