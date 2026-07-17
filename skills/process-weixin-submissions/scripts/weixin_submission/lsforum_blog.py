from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .publication import PublicationBlockerKind, PublicationError
from .schema_validation import validate_record
from .storage import WorkflowError, read_json


ALLOWED_TARGET_FIELDS = {
    "authorName",
    "authorTitle",
    "orgName",
    "postType",
    "category",
    "featured",
    "tags",
}


class LsforumPublicationAdapter:
    def __init__(self, config_path: Path, timeout_seconds: float = 10.0) -> None:
        config = read_json(config_path)
        validate_record("blog-config", config)
        base_url = config["base_url"]
        api_key_env = config["api_key_env"]
        targets = config["targets"]
        if not isinstance(base_url, str) or not base_url.startswith(
            ("http://", "https://")
        ):
            raise WorkflowError("Blog base_url must use http or https")
        if not isinstance(api_key_env, str) or not api_key_env.strip():
            raise WorkflowError("Blog api_key_env must be non-empty")
        if not isinstance(targets, dict):
            raise WorkflowError("Blog targets must be an object")
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.targets = targets
        self.timeout_seconds = timeout_seconds

    @property
    def adapter_id(self) -> str:
        return "lsforum_v1"

    def map_target(self, source_id: str) -> dict[str, Any]:
        mapped = self.targets.get(source_id)
        if not isinstance(mapped, dict):
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_missing",
                f"No Blog target mapping exists for {source_id}",
            )
        unknown = sorted(set(mapped) - ALLOWED_TARGET_FIELDS)
        if unknown:
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_invalid",
                f"Blog target mapping has unsupported fields: {unknown}",
            )
        author_name = mapped.get("authorName")
        if not isinstance(author_name, str) or not author_name.strip():
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_invalid",
                "Blog target mapping requires a non-empty authorName",
            )
        for field in ("authorTitle", "orgName", "category"):
            value = mapped.get(field)
            if value is not None and not isinstance(value, str):
                raise PublicationError(
                    PublicationBlockerKind.NEEDS_CONFIGURATION,
                    "target_mapping_invalid",
                    f"Blog target mapping field {field} must be a string",
                )
        if mapped.get("postType") not in (None, "article", "opinion"):
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_invalid",
                "Blog target mapping postType must be article or opinion",
            )
        if "featured" in mapped and not isinstance(mapped["featured"], bool):
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_invalid",
                "Blog target mapping featured must be boolean",
            )
        tags = mapped.get("tags")
        if tags is not None and (
            not isinstance(tags, list)
            or len(tags) > 12
            or not all(isinstance(tag, str) and tag.strip() for tag in tags)
        ):
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_invalid",
                "Blog target mapping tags must contain at most 12 non-empty strings",
            )
        return dict(mapped)

    def publish(self, request: dict[str, Any]) -> object:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "api_key_missing",
                f"Runtime secret {self.api_key_env} is missing",
            )
        title = request.get("title")
        content = request.get("body_markdown")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                "Blog title must contain 1 to 200 characters",
            )
        if not isinstance(content, str) or not content.strip():
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                "Blog content must be non-empty Markdown",
            )
        existing = self._get_slug(str(request["slug"]), preflight=True)
        if existing is not None:
            return self._recovered_response(request, existing)
        target = request["target"]
        if not isinstance(target, dict) or not isinstance(
            target.get("mapped_fields"), dict
        ):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                "Mapped target is invalid",
            )
        payload = {
            "title": request["title"],
            "content": request["body_markdown"],
            "slug": request["slug"],
            **target["mapped_fields"],
        }
        http_request = urllib.request.Request(
            f"{self.base_url}/posts",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=self.timeout_seconds
            ) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            body = error.read()
            if error.code >= 500:
                return self._recover_or_unknown(
                    request,
                    f"Blog returned HTTP {error.code}",
                    raw_response=_raw_http_error(error.code, body),
                )
            message = _error_message(body) or f"Blog returned HTTP {error.code}"
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                f"blog_http_{error.code}",
                message,
                _raw_http_error(error.code, body),
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            return self._recover_or_unknown(
                request, f"Blog POST outcome is unknown: {error}"
            )
        if status != 201:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_status_invalid",
                f"Expected HTTP 201, got {status}",
            )
        return _json_object(body, "Blog POST response")

    def normalize_response(self, raw_response: object) -> dict[str, Any]:
        if not isinstance(raw_response, dict):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response must be an object",
            )
        slug = raw_response.get("slug")
        url = raw_response.get("url")
        if raw_response.get("ok") is not True or not isinstance(slug, str) or not slug:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response lacks ok and slug",
            )
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response lacks a public URL",
            )
        return {
            "external_id": slug,
            "status": "published",
            "public_url": url,
            "slug": slug,
            "adapter": self.adapter_id,
        }

    def _recover_or_unknown(
        self,
        request: dict[str, Any],
        reason: str,
        raw_response: object | None = None,
    ) -> object:
        try:
            existing = self._get_slug(str(request["slug"]), preflight=False)
        except PublicationError:
            existing = None
        if existing is not None:
            return self._recovered_response(request, existing, unknown_outcome=True)
        raise PublicationError(
            PublicationBlockerKind.OUTCOME_UNKNOWN,
            "publication_outcome_unknown",
            reason,
            raw_response,
        )

    def _get_slug(self, slug: str, *, preflight: bool) -> dict[str, Any] | None:
        encoded_slug = urllib.parse.quote(slug, safe="")
        request = urllib.request.Request(
            f"{self.base_url}/posts/{encoded_slug}",
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                (
                    "publication_preflight_failed"
                    if preflight
                    else "publication_confirmation_failed"
                ),
                f"Blog lookup returned HTTP {error.code}",
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                (
                    "publication_preflight_failed"
                    if preflight
                    else "publication_confirmation_failed"
                ),
                f"Blog lookup failed: {error}",
            ) from error
        return _json_object(body, "Blog lookup response")

    def _recovered_response(
        self,
        request: dict[str, Any],
        existing: dict[str, Any],
        *,
        unknown_outcome: bool = False,
    ) -> dict[str, Any]:
        target = request.get("target")
        mapped_fields = (
            target.get("mapped_fields") if isinstance(target, dict) else None
        )
        expected_author = (
            mapped_fields.get("authorName") if isinstance(mapped_fields, dict) else None
        )
        observed_author = existing.get("authorName")
        if observed_author is None and isinstance(existing.get("author"), dict):
            observed_author = existing["author"].get("name")
        matches = (
            existing.get("slug") == request["slug"]
            and existing.get("title") == request["title"]
            and existing.get("content") == request["body_markdown"]
            and observed_author == expected_author
        )
        if not matches:
            raise PublicationError(
                (
                    PublicationBlockerKind.OUTCOME_UNKNOWN
                    if unknown_outcome
                    else PublicationBlockerKind.PERMANENT_FAILURE
                ),
                (
                    "publication_outcome_unknown"
                    if unknown_outcome
                    else "publication_slug_conflict"
                ),
                "The fixed slug could not be matched to the exact title, body, and author",
            )
        return {
            "ok": True,
            "slug": request["slug"],
            "url": existing.get(
                "url",
                f"{self.base_url.removesuffix('/api/v1')}/posts/{request['slug']}",
            ),
            "item": existing,
            "recovered": True,
        }


def _json_object(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationError(
            PublicationBlockerKind.PERMANENT_FAILURE,
            "blog_response_invalid",
            f"{label} is not JSON",
        ) from error
    if not isinstance(value, dict):
        raise PublicationError(
            PublicationBlockerKind.PERMANENT_FAILURE,
            "blog_response_invalid",
            f"{label} must be an object",
        )
    return value


def _error_message(body: bytes) -> str | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    message = value.get("message")
    return message if isinstance(message, str) else None


def _raw_http_error(status: int, body: bytes) -> dict[str, Any]:
    try:
        parsed_body: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed_body = body.decode("utf-8", errors="replace")
    return {"http_status": status, "body": parsed_body}
