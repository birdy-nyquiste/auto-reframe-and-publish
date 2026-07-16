from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .storage import WorkflowError, read_json


SCHEMA_VERSION = 2


@dataclass(frozen=True)
class StructuredSource:
    title: str
    body: str
    source_url: str | None
    images: tuple[str, ...]


@dataclass(frozen=True)
class Submission:
    window_id: str
    header_text: str
    target_id: str
    requirements: str | None
    source: StructuredSource


@dataclass(frozen=True)
class TaskHeader:
    target_id: str
    requirements: str | None
    article_count: int


class TaskHeaderError(WorkflowError):
    def __init__(
        self, reason: str, message: str, target_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.target_id = target_id


def require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{field} must be a non-empty string")
    return value


def parse_task_header(text: str) -> TaskHeader:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "#投稿":
        raise TaskHeaderError(
            "missing_submission_marker", "Task header must start with #投稿"
        )

    target_id: str | None = None
    requirements: str | None = None
    article_count = 1
    seen_fields: set[str] = set()
    for index, line in enumerate(lines[1:], start=1):
        if not line.strip():
            continue
        if ":" not in line:
            raise TaskHeaderError(
                "unknown_control_field",
                f"Unknown task-header line: {line}",
                target_id,
            )
        field, value = (part.strip() for part in line.split(":", 1))
        if field not in ("目标", "要求", "文章数"):
            raise TaskHeaderError(
                "unknown_control_field",
                f"Unknown task-header field: {field}",
                target_id,
            )
        if field in seen_fields:
            raise TaskHeaderError(
                "duplicate_control_field",
                f"Duplicate task-header field: {field}",
                target_id,
            )
        seen_fields.add(field)
        if field == "目标":
            target_id = value
            continue
        if field == "文章数":
            try:
                article_count = int(value)
            except ValueError as error:
                raise TaskHeaderError(
                    "unsupported_article_count",
                    "文章数 must be 1 in the current version",
                    target_id,
                ) from error
            if article_count != 1:
                raise TaskHeaderError(
                    "unsupported_article_count",
                    "Only one article is supported in the current version",
                    target_id,
                )
            continue
        if field == "要求":
            first_line = value
            remainder = "\n".join(lines[index + 1 :]).strip()
            requirements = "\n".join(part for part in (first_line, remainder) if part) or None
            break

    if not target_id:
        raise TaskHeaderError(
            "missing_target", "Task header is missing a non-empty target"
        )
    return TaskHeader(target_id, requirements, article_count)


def parse_submission_messages(messages_value: object, window_id: str) -> Submission:
    messages = messages_value
    if not isinstance(messages, list) or len(messages) != 2:
        raise WorkflowError("A submission candidate must contain exactly two messages")
    header, article = messages
    if not isinstance(header, dict) or header.get("kind") not in ("task_header", "text"):
        raise WorkflowError("The first message must be task-header text")
    if not isinstance(article, dict) or article.get("kind") != "official_account_article":
        raise WorkflowError("The second message must be an official_account_article")

    header_text = require_string(header.get("text"), "task header text")
    task_header = parse_task_header(header_text)
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
        target_id=task_header.target_id,
        requirements=task_header.requirements,
        source=StructuredSource(
            title=title,
            body=body,
            source_url=source_url_value,
            images=tuple(images_value),
        ),
    )


def structured_source_record(source: StructuredSource) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "title": source.title,
        "body": source.body,
        "source_url": source.source_url,
        "images": list(source.images),
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
