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
    "author",
    "authorExternalId",
    "authorSlug",
    "authorName",
    "authorTitle",
    "orgName",
    "orgSlug",
    "postType",
    "category",
    "featured",
    "tags",
}

ALLOWED_AUTHOR_FIELDS = {"externalId", "slug", "name", "title", "orgSlug"}
LEGACY_AUTHOR_FIELDS = (
    "authorExternalId",
    "authorSlug",
    "authorName",
    "authorTitle",
)

ALLOWED_PATCH_FIELDS = {
    "title",
    "content",
    "author",
    "authorExternalId",
    "authorSlug",
    "authorName",
    "excerpt",
    "postType",
    "category",
    "titleZh",
    "excerptZh",
    "contentZh",
    "authorTitle",
    "orgName",
    "orgSlug",
    "image",
    "sourceUrl",
    "readTime",
    "featured",
    "tags",
    "status",
}


def _author_object_error(author: object) -> str | None:
    if not isinstance(author, dict):
        return "author must be an object"
    unknown_fields = sorted(set(author) - ALLOWED_AUTHOR_FIELDS)
    if unknown_fields:
        return f"author has unsupported fields: {unknown_fields}"
    if not isinstance(author.get("name"), str) or not author["name"].strip():
        return "author requires a non-empty name"
    for field in ("externalId", "slug", "title", "orgSlug"):
        value = author.get(field)
        if value is not None and not isinstance(value, str):
            return f"author field {field} must be a string"
    return None


class LsforumContentApiAdapter:
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

    @property
    def destination_id(self) -> str:
        return self.base_url

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
        author = mapped.get("author")
        if author is not None:
            author_error = _author_object_error(author)
            if author_error is not None:
                raise PublicationError(
                    PublicationBlockerKind.NEEDS_CONFIGURATION,
                    "target_mapping_invalid",
                    f"Blog target mapping {author_error}",
                )
            conflicting_author_fields = sorted(
                field
                for field in LEGACY_AUTHOR_FIELDS
                if field in mapped
            )
            if conflicting_author_fields:
                raise PublicationError(
                    PublicationBlockerKind.NEEDS_CONFIGURATION,
                    "target_mapping_invalid",
                    (
                        "Blog target mapping author cannot be combined with legacy "
                        f"author fields: {conflicting_author_fields}"
                    ),
                )
        author_name = mapped.get("authorName")
        if author is None and (
            not isinstance(author_name, str) or not author_name.strip()
        ):
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "target_mapping_invalid",
                "Blog target mapping requires author or a non-empty authorName",
            )
        for field in (
            "authorExternalId",
            "authorSlug",
            "authorTitle",
            "orgSlug",
            "orgName",
            "category",
        ):
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

    def validate_request(self, request: dict[str, Any]) -> None:
        self._api_key()
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

    def _api_key(self) -> str:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key.strip():
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "api_key_missing",
                f"Runtime secret {self.api_key_env} is missing",
            )
        if (
            api_key != api_key.strip()
            or not api_key.isascii()
            or any(ord(character) < 33 or ord(character) > 126 for character in api_key)
            or api_key[0] in "\"'"
            or api_key[-1] in "\"'"
        ):
            raise PublicationError(
                PublicationBlockerKind.NEEDS_CONFIGURATION,
                "api_key_invalid_format",
                (
                    f"Runtime secret {self.api_key_env} must be an unquoted "
                    "printable ASCII value without surrounding whitespace"
                ),
            )
        return api_key

    def publish(self, request: dict[str, Any]) -> object:
        self.validate_request(request)
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
            "status": "published",
            **target["mapped_fields"],
        }
        try:
            response = self._send_http_request("POST", "/posts", payload=payload)
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
        status = response["http_status"]
        if status != 201:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_status_invalid",
                f"Expected HTTP 201, got {status}",
            )
        return response

    def confirm(self, request: dict[str, Any]) -> object:
        existing = self._get_slug(str(request["slug"]), preflight=False)
        if existing is None:
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                "publication_outcome_unknown",
                "The prior Blog publication attempt could not be confirmed",
            )
        return self._recovered_response(request, existing, unknown_outcome=True)

    def get_managed_post(self, slug: str) -> dict[str, Any]:
        response = self._content_api_request(
            "GET", f"/posts/{_encoded_slug(slug)}?manage=true"
        )
        if response is None:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_http_404",
                "Blog post was not found",
            )
        return response

    def patch_post(
        self, slug: str, changes: dict[str, Any], *, version: int | str
    ) -> dict[str, Any]:
        if not isinstance(changes, dict) or not changes:
            raise _invalid_management_request("Blog patch must be a non-empty object")
        unknown = sorted(set(changes) - ALLOWED_PATCH_FIELDS)
        if unknown:
            raise _invalid_management_request(
                f"Blog patch has unsupported fields: {unknown}"
            )
        status = changes.get("status")
        if status is not None and status not in ("draft", "published", "archived"):
            raise _invalid_management_request(
                "Blog patch status must be draft, published, or archived"
            )
        if "author" in changes:
            author_error = _author_object_error(changes["author"])
            if author_error is not None:
                raise _invalid_management_request(f"Blog patch {author_error}")
            conflicting_author_fields = sorted(
                field for field in LEGACY_AUTHOR_FIELDS if field in changes
            )
            if conflicting_author_fields:
                raise _invalid_management_request(
                    "Blog patch author cannot be combined with legacy author fields: "
                    f"{conflicting_author_fields}"
                )
        version_text = _version_text(version)
        response = self._content_api_request(
            "PATCH",
            f"/posts/{_encoded_slug(slug)}",
            payload=changes,
            extra_headers={"X-Post-Version": f'"{version_text}"'},
            side_effect=True,
        )
        if response is None:
            raise AssertionError("PATCH cannot return an absent response")
        return response

    def soft_delete_post(self, slug: str) -> dict[str, Any]:
        response = self._content_api_request(
            "DELETE", f"/posts/{_encoded_slug(slug)}", side_effect=True
        )
        if response is None:
            raise AssertionError("DELETE cannot return an absent response")
        return response

    def restore_post(self, slug: str) -> dict[str, Any]:
        response = self._content_api_request(
            "POST", f"/posts/{_encoded_slug(slug)}/restore", side_effect=True
        )
        if response is None:
            raise AssertionError("restore cannot return an absent response")
        return response

    def list_revisions(self, slug: str) -> dict[str, Any]:
        response = self._content_api_request(
            "GET", f"/posts/{_encoded_slug(slug)}/revisions"
        )
        if response is None:
            raise AssertionError("revisions cannot return an absent response")
        return response

    def normalize_response(self, raw_response: object) -> dict[str, Any]:
        response_body, response_etag = _response_parts(raw_response)
        if not isinstance(response_body, dict):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response must be an object",
            )
        slug = response_body.get("slug")
        url = response_body.get("url")
        if response_body.get("ok") is not True or not isinstance(slug, str) or not slug:
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
        item = response_body.get("item")
        item = item if isinstance(item, dict) else {}
        version = response_body.get("version", item.get("version"))
        etag = response_etag or response_body.get("etag") or response_body.get("ETag")
        content_status = response_body.get("status", item.get("status", "published"))
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response lacks a valid version",
            )
        if (
            (not isinstance(etag, str) or not etag)
            and response_body.get("recovered") is True
        ):
            etag = f'"{version}"'
        if not isinstance(etag, str) or not etag:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response lacks an ETag",
            )
        if content_status != "published":
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog publication response is not published",
            )
        return {
            "external_id": slug,
            "status": "published",
            "content_status": content_status,
            "public_url": url,
            "slug": slug,
            "adapter": self.adapter_id,
            "version": version,
            "etag": etag,
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

    def _content_api_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        allow_not_found: bool = False,
        side_effect: bool = False,
    ) -> dict[str, Any] | None:
        try:
            response = self._send_http_request(
                method, path, payload=payload, extra_headers=extra_headers
            )
        except urllib.error.HTTPError as error:
            body = error.read()
            if error.code == 404 and allow_not_found:
                return None
            if error.code == 412:
                raise PublicationError(
                    PublicationBlockerKind.PERMANENT_FAILURE,
                    "blog_version_conflict",
                    _error_message(body) or "Blog version is stale",
                    _raw_http_error(error.code, body),
                ) from error
            if error.code == 428:
                raise PublicationError(
                    PublicationBlockerKind.PERMANENT_FAILURE,
                    "blog_version_required",
                    _error_message(body) or "Blog version header is required",
                    _raw_http_error(error.code, body),
                ) from error
            raise PublicationError(
                (
                    PublicationBlockerKind.OUTCOME_UNKNOWN
                    if side_effect and error.code >= 500
                    else PublicationBlockerKind.PERMANENT_FAILURE
                ),
                f"blog_http_{error.code}",
                _error_message(body) or f"Blog returned HTTP {error.code}",
                _raw_http_error(error.code, body),
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise PublicationError(
                (
                    PublicationBlockerKind.OUTCOME_UNKNOWN
                    if side_effect
                    else PublicationBlockerKind.PERMANENT_FAILURE
                ),
                "blog_management_outcome_unknown" if side_effect else "blog_read_failed",
                f"Blog {method} failed: {error}",
            ) from error
        status = response["http_status"]
        if status < 200 or status >= 300:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_status_invalid",
                f"Expected a successful response, got {status}",
            )
        return response

    def _send_http_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        api_key = self._api_key()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            **(extra_headers or {}),
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=headers
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return _http_response(
                response.status,
                response.read(),
                response.headers.get("ETag"),
                f"Blog {method} response",
            )

    def _get_slug(self, slug: str, *, preflight: bool) -> dict[str, Any] | None:
        try:
            return self._content_api_request(
                "GET",
                f"/posts/{_encoded_slug(slug)}?manage=true",
                allow_not_found=True,
            )
        except PublicationError as error:
            if error.blocker_kind is PublicationBlockerKind.NEEDS_CONFIGURATION:
                raise
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                (
                    "publication_preflight_failed"
                    if preflight
                    else "publication_confirmation_failed"
                ),
                f"Blog lookup failed: {error}",
                error.raw_response,
            ) from error

    def _recovered_response(
        self,
        request: dict[str, Any],
        existing: dict[str, Any],
        *,
        unknown_outcome: bool = False,
    ) -> dict[str, Any]:
        existing_body, existing_etag = _response_parts(existing)
        if not isinstance(existing_body, dict):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog lookup response must be an object",
            )
        target = request.get("target")
        mapped_fields = (
            target.get("mapped_fields") if isinstance(target, dict) else None
        )
        expected_author = (
            mapped_fields.get("authorName") if isinstance(mapped_fields, dict) else None
        )
        if (
            expected_author is None
            and isinstance(mapped_fields, dict)
            and isinstance(mapped_fields.get("author"), dict)
        ):
            expected_author = mapped_fields["author"].get("name")
        observed_author = existing_body.get("authorName")
        if observed_author is None and isinstance(existing_body.get("author"), dict):
            observed_author = existing_body["author"].get("name")
        matches = (
            existing_body.get("slug") == request["slug"]
            and existing_body.get("title") == request["title"]
            and existing_body.get("content") == request["body_markdown"]
            and observed_author == expected_author
            and existing_body.get("status") == "published"
            and _explicitly_undeleted(existing_body)
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
                (
                    "The fixed slug could not be matched to the exact title, body, "
                    "author, and published state"
                ),
            )
        return {
            "http_status": existing.get("http_status", 200),
            "headers": {"etag": existing_etag},
            "body": {
                "ok": True,
                "slug": request["slug"],
                "url": existing_body.get(
                    "url",
                    f"{self.base_url.removesuffix('/api/v1')}/posts/{request['slug']}",
                ),
                "item": existing_body,
                "version": existing_body.get("version"),
                "status": existing_body.get("status"),
                "recovered": True,
            },
        }


LsforumPublicationAdapter = LsforumContentApiAdapter


def _json_object(body: bytes, label: str) -> dict[str, Any]:
    value = _json_value(body, label)
    if not isinstance(value, dict):
        raise PublicationError(
            PublicationBlockerKind.PERMANENT_FAILURE,
            "blog_response_invalid",
            f"{label} must be an object",
        )
    return value


def _json_value(body: bytes, label: str) -> object:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationError(
            PublicationBlockerKind.PERMANENT_FAILURE,
            "blog_response_invalid",
            f"{label} is not JSON",
        ) from error
    return value


def _http_response(
    status: int, body: bytes, etag: str | None, label: str
) -> dict[str, Any]:
    parsed_body: object = _json_value(body, label) if body else None
    headers: dict[str, str] = {}
    if etag is not None:
        headers["etag"] = etag
    return {"http_status": status, "headers": headers, "body": parsed_body}


def _response_parts(raw_response: object) -> tuple[object, str | None]:
    if not isinstance(raw_response, dict):
        return raw_response, None
    if "http_status" not in raw_response:
        etag = raw_response.get("etag") or raw_response.get("ETag")
        return raw_response, etag if isinstance(etag, str) else None
    headers = raw_response.get("headers")
    etag = headers.get("etag") if isinstance(headers, dict) else None
    return raw_response.get("body"), etag if isinstance(etag, str) else None


def _invalid_management_request(message: str) -> PublicationError:
    return PublicationError(
        PublicationBlockerKind.PERMANENT_FAILURE,
        "publication_request_invalid",
        message,
    )


def _encoded_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug.strip():
        raise _invalid_management_request("Blog slug must be non-empty")
    return urllib.parse.quote(slug, safe="")


def _version_text(version: int | str) -> str:
    if isinstance(version, bool):
        raise _invalid_management_request("Blog version must be a positive integer")
    if isinstance(version, int):
        if version < 1:
            raise _invalid_management_request("Blog version must be a positive integer")
        return str(version)
    if (
        not isinstance(version, str)
        or not version
        or not version.isascii()
        or any(character in version for character in ('"', "\r", "\n"))
    ):
        raise _invalid_management_request("Blog version has an invalid format")
    return version


def _explicitly_undeleted(post: dict[str, Any]) -> bool:
    if "deleted" in post:
        return post["deleted"] is False
    if "isDeleted" in post:
        return post["isDeleted"] is False
    if "deletedAt" in post:
        return post["deletedAt"] is None
    return False


def _error_message(body: bytes) -> str | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    message = value.get("message")
    if not isinstance(message, str) and isinstance(value.get("error"), dict):
        message = value["error"].get("message")
    return message if isinstance(message, str) else None


def _raw_http_error(status: int, body: bytes) -> dict[str, Any]:
    try:
        parsed_body: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed_body = body.decode("utf-8", errors="replace")
    return {"http_status": status, "body": parsed_body}
