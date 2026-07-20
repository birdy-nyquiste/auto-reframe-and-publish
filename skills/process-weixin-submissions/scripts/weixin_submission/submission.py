from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .storage import WorkflowError


SCHEMA_VERSION = 2


@dataclass(frozen=True)
class StructuredSource:
    title: str
    body: str
    source_url: str | None
    images: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    media_limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptureInput:
    adapter: str
    article_end_method: str
    clipboard_text: str
    source_url: str | None
    article_end_observed: bool
    all_static_images_captured: bool
    media: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Submission:
    window_id: str
    header_text: str
    target_id: str
    requirements: str | None
    title: str
    capture: CaptureInput


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
    scripted_capture = article.get("scripted_capture")
    computer_use_capture = article.get("computer_use_capture")
    if scripted_capture is not None and computer_use_capture is not None:
        raise WorkflowError(
            "An article cannot contain both scripted_capture and computer_use_capture"
        )
    captured_content = (
        computer_use_capture
        if computer_use_capture is not None
        else scripted_capture
    )
    if captured_content is None:
        body = require_string(article.get("body"), "article body")
        source_url_value = article.get("source_url")
        images_value = article.get("images", [])
        if images_value:
            raise WorkflowError(
                "Legacy scripted articles with images must use scripted_capture"
            )
        capture = CaptureInput(
            "scripted_capture",
            "scripted_fixture",
            body,
            _optional_url(source_url_value),
            True,
            True,
            (),
        )
    else:
        if not isinstance(captured_content, dict):
            raise WorkflowError("captured article content must be an object")
        body = require_string(
            captured_content.get("clipboard_text"), "captured clipboard text"
        )
        source_url_value = captured_content.get("source_url")
        article_end_observed = captured_content.get("article_end_observed")
        if not isinstance(article_end_observed, bool):
            raise WorkflowError("article_end_observed must be boolean")
        all_static_images_captured = captured_content.get(
            "all_static_images_captured"
        )
        if not isinstance(all_static_images_captured, bool):
            raise WorkflowError("all_static_images_captured must be boolean")
        media_value = captured_content.get("media", [])
        if not isinstance(media_value, list) or not all(
            isinstance(item, dict) for item in media_value
        ):
            raise WorkflowError("scripted capture media must be a list of objects")
        is_computer_use_capture = computer_use_capture is not None
        capture = CaptureInput(
            (
                "macos_computer_use_v1"
                if is_computer_use_capture
                else "scripted_capture"
            ),
            (
                "computer_use_visual_confirmation"
                if is_computer_use_capture
                else "scripted_fixture"
            ),
            body,
            _optional_url(source_url_value),
            article_end_observed,
            all_static_images_captured,
            tuple(media_value),
        )

    return Submission(
        window_id=window_id,
        header_text=header_text,
        target_id=task_header.target_id,
        requirements=task_header.requirements,
        title=title,
        capture=capture,
    )


def _optional_url(value: object) -> str | None:
    source_url_value = value
    if source_url_value is not None and not isinstance(source_url_value, str):
        raise WorkflowError("source_url must be a string or null")
    return source_url_value
