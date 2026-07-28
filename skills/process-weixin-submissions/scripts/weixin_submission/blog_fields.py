from __future__ import annotations

from copy import deepcopy
from typing import Any

from .storage import WorkflowError


STRING_FIELDS = {
    "author.name",
    "author.slug",
    "category",
}
ENUM_FIELDS = {"postType": {"article", "opinion"}}
BOOLEAN_FIELDS = {"featured"}
ARRAY_FIELDS = {"tags"}
ALLOWED_INPUT_FIELDS = STRING_FIELDS | set(ENUM_FIELDS) | BOOLEAN_FIELDS | ARRAY_FIELDS
PROTECTED_INPUT_FIELDS = {
    "title",
    "content",
    "titleZh",
    "contentZh",
    "excerpt",
    "excerptZh",
    "image",
    "sourceUrl",
    "readTime",
    "slug",
    "status",
}


class BlogFieldError(WorkflowError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def parse_blog_field(field: str, value: str) -> tuple[str, Any]:
    if field in PROTECTED_INPUT_FIELDS:
        raise BlogFieldError(
            "protected_blog_field",
            f"Blog field {field} is owned by the workflow and cannot appear in #投稿",
        )
    if field not in ALLOWED_INPUT_FIELDS:
        raise BlogFieldError(
            "unknown_control_field", f"Unknown task-header field: {field}"
        )
    if field in STRING_FIELDS:
        if not value:
            if field == "author.name":
                raise BlogFieldError(
                    "missing_author_name",
                    "Task header requires a non-empty author.name",
                )
            raise BlogFieldError(
                "invalid_blog_field", f"Blog field {field} must be non-empty"
            )
        if value != value.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise BlogFieldError(
                "invalid_blog_field",
                f"Blog field {field} contains invalid whitespace or control characters",
            )
        return field, value
    if field in ENUM_FIELDS:
        if value not in ENUM_FIELDS[field]:
            allowed = ", ".join(sorted(ENUM_FIELDS[field]))
            raise BlogFieldError(
                "invalid_blog_field", f"Blog field {field} must be one of: {allowed}"
            )
        return field, value
    if field in BOOLEAN_FIELDS:
        if value not in ("true", "false"):
            raise BlogFieldError(
                "invalid_blog_field", f"Blog field {field} must be true or false"
            )
        return field, value == "true"
    tags = [item.strip() for item in value.split(",")]
    if not tags or len(tags) > 12 or any(not item for item in tags):
        raise BlogFieldError(
            "invalid_blog_field",
            "Blog field tags must contain 1 to 12 comma-separated non-empty values",
        )
    return field, tags


def assign_blog_field(fields: dict[str, Any], path: str, value: Any) -> None:
    if path.startswith("author."):
        author = fields.setdefault("author", {})
        if not isinstance(author, dict):
            raise BlogFieldError("invalid_blog_field", "Blog author must be an object")
        author[path.removeprefix("author.")] = value
        return
    fields[path] = value


def validate_publication_fields(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BlogFieldError(
            "invalid_blog_field", "Blog publication fields must be an object"
        )
    fields: dict[str, Any] = {}
    for top_level, raw_value in value.items():
        if top_level == "author":
            if not isinstance(raw_value, dict):
                raise BlogFieldError(
                    "invalid_blog_field", "Blog author must be an object"
                )
            for author_field, author_value in raw_value.items():
                path = f"author.{author_field}"
                if not isinstance(author_value, str):
                    raise BlogFieldError(
                        "invalid_blog_field", f"Blog field {path} must be a string"
                    )
                parsed_path, parsed = parse_blog_field(path, author_value)
                assign_blog_field(fields, parsed_path, parsed)
            continue
        if top_level not in ALLOWED_INPUT_FIELDS:
            raise BlogFieldError(
                "invalid_blog_field",
                f"Unsupported Blog publication field: {top_level}",
            )
        if top_level in BOOLEAN_FIELDS:
            if not isinstance(raw_value, bool):
                raise BlogFieldError(
                    "invalid_blog_field",
                    f"Blog field {top_level} must be boolean",
                )
            fields[top_level] = raw_value
            continue
        if top_level in ARRAY_FIELDS:
            if (
                not isinstance(raw_value, list)
                or len(raw_value) < 1
                or len(raw_value) > 12
                or not all(isinstance(item, str) and item.strip() for item in raw_value)
            ):
                raise BlogFieldError(
                    "invalid_blog_field",
                    "Blog field tags must contain 1 to 12 non-empty strings",
                )
            fields[top_level] = list(raw_value)
            continue
        if not isinstance(raw_value, str):
            raise BlogFieldError(
                "invalid_blog_field", f"Blog field {top_level} must be a string"
            )
        parsed_path, parsed = parse_blog_field(top_level, raw_value)
        assign_blog_field(fields, parsed_path, parsed)
    author = fields.get("author")
    if (
        not isinstance(author, dict)
        or not isinstance(author.get("name"), str)
        or not author["name"]
    ):
        raise BlogFieldError(
            "missing_author_name", "Task header requires a non-empty author.name"
        )
    return deepcopy(fields)
