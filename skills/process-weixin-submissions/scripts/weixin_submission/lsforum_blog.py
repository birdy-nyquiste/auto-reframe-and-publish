from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .blog_fields import BlogFieldError, validate_publication_fields
from .publication import PublicationBlockerKind, PublicationError
from .schema_validation import validate_record
from .storage import WorkflowError, read_json


class LsforumContentApiAdapter:
    def __init__(self, config_path: Path, timeout_seconds: float = 10.0) -> None:
        config = read_json(config_path)
        validate_record("blog-config", config)
        base_url = config["base_url"]
        api_key_env = config["api_key_env"]
        if not isinstance(base_url, str) or not base_url.startswith(
            ("http://", "https://")
        ):
            raise WorkflowError("Blog base_url must use http or https")
        if not isinstance(api_key_env, str) or not api_key_env.strip():
            raise WorkflowError("Blog api_key_env must be non-empty")
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    @property
    def adapter_id(self) -> str:
        return "lsforum_v1"

    @property
    def destination_id(self) -> str:
        return self.base_url

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
        try:
            validate_publication_fields(request.get("publication_fields"))
        except BlogFieldError as error:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                str(error),
            ) from error
        images = request.get("images")
        if not isinstance(images, list) or not all(
            isinstance(url, str) and url.startswith("https://") for url in images
        ):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                "Blog images must be HTTPS URLs",
            )
        cover_image = request.get("cover_image")
        if cover_image is not None and (
            not isinstance(cover_image, str)
            or not cover_image.startswith("https://")
            or cover_image not in images
        ):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                "Blog cover image must be one of the uploaded HTTPS image URLs",
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
        try:
            publication_fields = validate_publication_fields(
                request.get("publication_fields")
            )
        except BlogFieldError as error:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_request_invalid",
                str(error),
            ) from error
        payload = {
            "title": request["title"],
            "content": request["body_markdown"],
            "slug": request["slug"],
            "status": "published",
            **publication_fields,
        }
        if request.get("cover_image") is not None:
            payload["image"] = request["cover_image"]
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

    def normalize_response(self, raw_response: object) -> dict[str, Any]:
        response_body = _response_body(raw_response)
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
        content_status = response_body.get("status", item.get("status", "published"))
        if version is None and response_body.get("recovered") is not True:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog POST response lacks a version",
            )
        if version is not None and (
            not isinstance(version, int) or isinstance(version, bool) or version < 1
        ):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog response has an invalid version",
            )
        if content_status != "published":
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog publication response is not published",
            )
        normalized = {
            "external_id": slug,
            "status": "published",
            "content_status": content_status,
            "public_url": url,
            "slug": slug,
            "adapter": self.adapter_id,
        }
        if version is not None:
            normalized["version"] = version
        return normalized

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
        allow_not_found: bool = False,
        authenticated: bool = True,
    ) -> dict[str, Any] | None:
        try:
            response = self._send_http_request(
                method, path, payload=payload, authenticated=authenticated
            )
        except urllib.error.HTTPError as error:
            body = error.read()
            if error.code == 404 and allow_not_found:
                return None
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                f"blog_http_{error.code}",
                _error_message(body) or f"Blog returned HTTP {error.code}",
                _raw_http_error(error.code, body),
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_read_failed",
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
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._api_key()}"
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
                f"Blog {method} response",
            )

    def _get_slug(self, slug: str, *, preflight: bool) -> dict[str, Any] | None:
        try:
            return self._content_api_request(
                "GET",
                f"/posts/{_encoded_slug(slug)}",
                allow_not_found=True,
                authenticated=False,
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
        existing_body = _response_body(existing)
        if not isinstance(existing_body, dict):
            raise PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "blog_response_invalid",
                "Blog lookup response must be an object",
            )
        publication_fields = request.get("publication_fields")
        expected_author = (
            publication_fields["author"].get("name")
            if isinstance(publication_fields, dict)
            and isinstance(publication_fields.get("author"), dict)
            else None
        )
        observed_author = existing_body.get("authorName")
        if observed_author is None and isinstance(existing_body.get("author"), dict):
            observed_author = existing_body["author"].get("name")
        matches = (
            existing_body.get("slug") == request["slug"]
            and existing_body.get("title") == request["title"]
            and existing_body.get("content") == request["body_markdown"]
            and observed_author == expected_author
            and existing_body.get("image") == request.get("cover_image")
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
                    "author, and cover image in the public Blog response"
                ),
            )
        observed_url = existing_body.get("url")
        public_url = (
            observed_url
            if isinstance(observed_url, str)
            and observed_url.startswith(("http://", "https://"))
            else f"{self.base_url.removesuffix('/api/v1')}/posts/{request['slug']}"
        )
        return {
            "http_status": existing.get("http_status", 200),
            "headers": {},
            "body": {
                "ok": True,
                "slug": request["slug"],
                "url": public_url,
                "item": existing_body,
                "status": "published",
                "recovered": True,
            },
        }


LsforumPublicationAdapter = LsforumContentApiAdapter


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


def _http_response(status: int, body: bytes, label: str) -> dict[str, Any]:
    parsed_body: object = _json_value(body, label) if body else None
    return {"http_status": status, "headers": {}, "body": parsed_body}


def _response_body(raw_response: object) -> object:
    if not isinstance(raw_response, dict):
        return raw_response
    if "http_status" not in raw_response:
        return raw_response
    return raw_response.get("body")


def _invalid_slug(message: str) -> PublicationError:
    return PublicationError(
        PublicationBlockerKind.PERMANENT_FAILURE,
        "publication_request_invalid",
        message,
    )


def _encoded_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug.strip():
        raise _invalid_slug("Blog slug must be non-empty")
    return urllib.parse.quote(slug, safe="")


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
