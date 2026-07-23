from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from .blog_fields import BlogFieldError, validate_publication_fields
from .blob_upload import BlobUploadError, ImageUploader, validate_image_bytes
from .rewrite import RewriteArtifact, load_rewrite_artifact
from .schema_validation import (
    SchemaValidationError,
    publication_allowed_transitions,
    validate_record,
)
from .state import load_record, save_record
from .storage import (
    WorkflowError,
    new_id,
    read_json,
    utc_now,
    write_immutable_bytes,
    write_json,
)
from .submission import SCHEMA_VERSION


class PublicationAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    @property
    def destination_id(self) -> str: ...

    def validate_request(self, request: dict[str, Any]) -> None: ...

    def publish(self, request: dict[str, Any]) -> object: ...

    def confirm(self, request: dict[str, Any]) -> object: ...

    def normalize_response(self, raw_response: object) -> dict[str, Any]: ...


class PublicationBlockerKind(str, Enum):
    NEEDS_CONFIGURATION = "needs_configuration"
    PERMANENT_FAILURE = "permanent_failure"
    OUTCOME_UNKNOWN = "outcome_unknown"


class PublicationImagePolicy(str, Enum):
    PRESERVE = "preserve"
    OMIT = "omit"
    UPLOAD = "upload"

    @property
    def requires_uploader(self) -> bool:
        return self is PublicationImagePolicy.UPLOAD

    @classmethod
    def parse(cls, value: str) -> "PublicationImagePolicy":
        try:
            return cls(value)
        except ValueError as error:
            raise WorkflowError(
                f"Unsupported publication image policy: {value}"
            ) from error


class PublicationError(WorkflowError):
    def __init__(
        self,
        blocker_kind: PublicationBlockerKind,
        code: str,
        message: str,
        raw_response: object | None = None,
    ) -> None:
        super().__init__(message)
        self.blocker_kind = blocker_kind
        self.code = code
        self.raw_response = raw_response


class FakePublicationAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def adapter_id(self) -> str:
        return "fake_publication"

    @property
    def destination_id(self) -> str:
        return self.directory.resolve().as_uri()

    def validate_request(self, request: dict[str, Any]) -> None:
        return

    def publish(self, request: dict[str, Any]) -> object:
        configured_failure = self._take_failure()
        if configured_failure is not None:
            try:
                blocker_kind = PublicationBlockerKind(
                    str(configured_failure.get("kind", "permanent_failure"))
                )
            except ValueError as error:
                raise WorkflowError(
                    "Fake publication failure has an invalid blocker kind"
                ) from error
            raise PublicationError(
                blocker_kind,
                str(configured_failure.get("code", "fake_publication_failed")),
                str(configured_failure.get("message", "Fake publication failed")),
            )
        publication_id = str(request["publication_id"])
        idempotency_path = self.directory / "idempotency" / f"{publication_id}.json"
        if idempotency_path.exists():
            prior = read_json(idempotency_path)
            if prior.get("request") != request:
                raise WorkflowError(
                    "Fake publication ID was reused with another request"
                )
            return prior["response"]
        response = {
            "external_id": f"post-{publication_id}",
            "status": "published",
            "content_status": "published",
            "public_url": f"https://blog.example.test/posts/{request['slug']}",
            "slug": request["slug"],
            "adapter": self.adapter_id,
            "version": 1,
            "etag": '"1"',
        }
        write_json(
            self.directory / "posts" / f"{publication_id}.json",
            {"request": request, "response": response},
        )
        write_json(idempotency_path, {"request": request, "response": response})
        return response

    def confirm(self, request: dict[str, Any]) -> object:
        publication_id = str(request["publication_id"])
        idempotency_path = self.directory / "idempotency" / f"{publication_id}.json"
        if not idempotency_path.exists():
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                "publication_outcome_unknown",
                "The prior fake publication attempt could not be confirmed",
            )
        prior = read_json(idempotency_path)
        if prior.get("request") != request:
            raise PublicationError(
                PublicationBlockerKind.OUTCOME_UNKNOWN,
                "publication_outcome_unknown",
                "The prior fake publication request no longer matches",
            )
        return prior["response"]

    def normalize_response(self, raw_response: object) -> dict[str, Any]:
        if not isinstance(raw_response, dict):
            raise WorkflowError("Fake publication response must be an object")
        normalized = dict(raw_response)
        validate_record("publication-response", normalized)
        return normalized

    def _take_failure(self) -> dict[str, Any] | None:
        control_path = self.directory / "control.json"
        if not control_path.exists():
            return None
        control = read_json(control_path)
        failures = control.get("publish_failures", [])
        if not isinstance(failures, list) or not failures:
            return None
        failure = failures.pop(0)
        if not isinstance(failure, dict):
            raise WorkflowError("Fake publication failure must be an object")
        control["publish_failures"] = failures
        write_json(control_path, control)
        return failure


def publish_rewrite(
    repository: Path,
    task_id: str,
    run_id: str,
    adapter: PublicationAdapter,
    before_send: Callable[[], None] | None = None,
    after_send_started: Callable[[], None] | None = None,
    after_response_received: Callable[[], None] | None = None,
    image_policy: str = "preserve",
    image_uploader: ImageUploader | None = None,
    cover_image: str | None = None,
) -> tuple[str, dict[str, Any]]:
    policy = PublicationImagePolicy.parse(image_policy)
    task_directory = repository / "tasks" / task_id
    task = load_record("task", task_directory / "task.json")
    if task["milestone"] != "rewrite_artifact_ready" or task["blocker"] is not None:
        raise WorkflowError(f"Task {task_id} has no publishable rewrite artifact")
    target_id = task["target_id"]
    if not isinstance(target_id, str):
        raise WorkflowError(f"Task {task_id} has no target ID")
    try:
        publication_fields = validate_publication_fields(task.get("publication_fields"))
    except BlogFieldError as error:
        raise WorkflowError(
            f"Task {task_id} has invalid Blog publication fields: {error}"
        ) from error
    artifact = load_rewrite_artifact(task_directory, target_id, task["requirements"])
    image_plan: dict[str, Any] | None = None
    if policy.requires_uploader:
        if image_uploader is None:
            raise WorkflowError("Image upload policy requires a Blob uploader")
        image_plan = _build_image_plan(
            task_directory,
            artifact,
            cover_image=cover_image,
            destination=image_uploader.destination_id,
        )
        publication_body = artifact.content
        presentation = None
    else:
        publication_body, presentation = _publication_body(artifact, policy)
    commit_bytes = (task_directory / "rewrite" / "commit.json").read_bytes()
    publication_id = new_id("publication")
    publication_directory = repository / "publications" / publication_id
    now = utc_now()
    publication: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "publication_id": publication_id,
        "created_in_run": run_id,
        "created_at": now,
        "updated_at": now,
        "task_id": task_id,
        "rewrite_commit_sha256": hashlib.sha256(commit_bytes).hexdigest(),
        "target_id": target_id,
        "slug": _slug(publication_id),
        "adapter": adapter.adapter_id,
        "destination": adapter.destination_id,
        "milestone": "publication_created",
        "blocker": None,
        "external_result": None,
    }
    if presentation is not None:
        publication["presentation"] = presentation
    if image_plan is not None:
        publication["image_plan"] = image_plan
    _commit_publication(
        publication_directory, publication, run_id, "milestone_committed"
    )

    if artifact.images and policy is PublicationImagePolicy.PRESERVE:
        publication["blocker"] = {
            "kind": "needs_configuration",
            "error_code": "public_image_urls_missing",
            "message": "The rewrite contains local images without stable public URLs",
        }
        publication["updated_at"] = utc_now()
        _commit_publication(publication_directory, publication, run_id, "blocked")
        return publication_id, _result(publication)

    image_urls: list[str] = []
    cover_image_url: str | None = None
    if policy.requires_uploader:
        if image_uploader is None or image_plan is None:
            raise AssertionError("Upload publication lacks its resolved dependencies")
        try:
            uploaded = _upload_planned_images(
                task_directory,
                publication_directory,
                publication,
                run_id,
                image_plan,
                image_uploader,
            )
            publication_body, presentation = _publication_body(
                artifact, "upload", uploaded
            )
        except BlobUploadError as error:
            _block(
                publication_directory,
                publication,
                run_id,
                PublicationError(
                    (
                        PublicationBlockerKind.NEEDS_CONFIGURATION
                        if error.needs_configuration
                        else PublicationBlockerKind.PERMANENT_FAILURE
                    ),
                    error.code,
                    str(error),
                ),
            )
            return publication_id, _result(publication)
        write_immutable_bytes(
            publication_directory / "image-assets.json", _json_bytes(uploaded)
        )
        publication["presentation"] = presentation
        publication["updated_at"] = utc_now()
        _commit_publication(
            publication_directory, publication, run_id, "images_resolved"
        )
        image_urls = [str(item["url"]) for item in uploaded]
        cover_image_url = presentation["cover_image_url"]

    return publication_id, _prepare_and_execute_publication(
        publication_directory,
        publication,
        artifact,
        publication_fields,
        publication_body,
        run_id,
        adapter,
        image_urls=image_urls,
        cover_image_url=cover_image_url,
        before_send=before_send,
        after_send_started=after_send_started,
        after_response_received=after_response_received,
    )


def _prepare_and_execute_publication(
    publication_directory: Path,
    publication: dict[str, Any],
    artifact: RewriteArtifact,
    publication_fields: dict[str, Any],
    publication_body: str,
    run_id: str,
    adapter: PublicationAdapter,
    *,
    image_urls: list[str],
    cover_image_url: str | None,
    before_send: Callable[[], None] | None = None,
    after_send_started: Callable[[], None] | None = None,
    after_response_received: Callable[[], None] | None = None,
) -> dict[str, Any]:
    try:
        request = _request(
            publication,
            artifact,
            publication_fields,
            publication_body,
            adapter,
            image_urls=image_urls,
            cover_image_url=cover_image_url,
        )
    except PublicationError as error:
        _block(publication_directory, publication, run_id, error)
        return _result(publication)
    request_bytes = _json_bytes(request)
    write_immutable_bytes(publication_directory / "request.json", request_bytes)
    write_immutable_bytes(
        publication_directory / "attempts" / run_id / "request.json", request_bytes
    )
    _write_attempt_marker(
        publication_directory / "attempts" / run_id / "prepared.json",
        "prepared",
        request_bytes,
    )
    publication["milestone"] = "request_ready"
    publication["updated_at"] = utc_now()
    _commit_publication(
        publication_directory, publication, run_id, "milestone_committed"
    )

    try:
        adapter.validate_request(request)
    except PublicationError as error:
        _record_publication_error(
            publication_directory, publication, run_id, error
        )
        return _result(publication)
    if before_send is not None:
        before_send()
    return _execute_post_attempt(
        publication_directory,
        publication,
        run_id,
        adapter,
        request,
        after_send_started=after_send_started,
        after_response_received=after_response_received,
    )


def resume_planned_image_publication(
    repository: Path,
    task_id: str,
    run_id: str,
    adapter: PublicationAdapter,
    image_uploader: ImageUploader,
) -> tuple[str, dict[str, Any]] | None:
    publications_directory = repository / "publications"
    if not publications_directory.exists():
        return None
    for publication_directory in sorted(publications_directory.iterdir()):
        if not publication_directory.is_dir():
            continue
        publication = validate_publication_history(publication_directory)
        if (
            publication["task_id"] != task_id
            or publication["adapter"] != adapter.adapter_id
            or publication["milestone"] != "publication_created"
            or publication["blocker"] is not None
            or not isinstance(publication.get("image_plan"), dict)
        ):
            continue
        if publication.get("destination") != adapter.destination_id:
            raise WorkflowError(
                "Pending image publication belongs to another Blog destination"
            )
        image_plan = publication["image_plan"]
        if image_plan.get("destination") != image_uploader.destination_id:
            raise WorkflowError(
                "Pending image publication belongs to another Blob destination"
            )
        task_directory = repository / "tasks" / task_id
        task = load_record("task", task_directory / "task.json")
        if (
            task["milestone"] != "rewrite_artifact_ready"
            or task["blocker"] is not None
            or task["target_id"] != publication["target_id"]
        ):
            raise WorkflowError("Pending image publication no longer matches its task")
        commit_bytes = (task_directory / "rewrite" / "commit.json").read_bytes()
        if hashlib.sha256(commit_bytes).hexdigest() != publication["rewrite_commit_sha256"]:
            raise WorkflowError("Pending image publication rewrite commit changed")
        artifact = load_rewrite_artifact(
            task_directory, str(task["target_id"]), task["requirements"]
        )
        publication_fields = validate_publication_fields(task.get("publication_fields"))
        try:
            uploaded = _upload_planned_images(
                task_directory,
                publication_directory,
                publication,
                run_id,
                image_plan,
                image_uploader,
            )
            publication_body, expected_presentation = _publication_body(
                artifact, "upload", uploaded
            )
        except BlobUploadError as error:
            _block(
                publication_directory,
                publication,
                run_id,
                PublicationError(
                    (
                        PublicationBlockerKind.NEEDS_CONFIGURATION
                        if error.needs_configuration
                        else PublicationBlockerKind.PERMANENT_FAILURE
                    ),
                    error.code,
                    str(error),
                ),
            )
            return str(publication["publication_id"]), _result(publication)
        presentation = publication.get("presentation")
        if presentation is None:
            write_immutable_bytes(
                publication_directory / "image-assets.json", _json_bytes(uploaded)
            )
            publication["presentation"] = expected_presentation
            publication["updated_at"] = utc_now()
            _commit_publication(
                publication_directory, publication, run_id, "images_resolved"
            )
        elif presentation != expected_presentation:
            raise WorkflowError(
                "Pending image publication presentation failed integrity validation"
            )
        result = _prepare_and_execute_publication(
            publication_directory,
            publication,
            artifact,
            publication_fields,
            publication_body,
            run_id,
            adapter,
            image_urls=[str(item["url"]) for item in uploaded],
            cover_image_url=expected_presentation["cover_image_url"],
        )
        return str(publication["publication_id"]), result
    return None


def resume_ready_publications(
    repository: Path,
    run_id: str,
    adapter: PublicationAdapter,
) -> list[tuple[str, dict[str, Any]]]:
    resumed: list[tuple[str, dict[str, Any]]] = []
    for publication_directory in sorted((repository / "publications").iterdir()):
        if not publication_directory.is_dir():
            continue
        try:
            publication = validate_publication_history(publication_directory)
        except (WorkflowError, SchemaValidationError, OSError):
            resumed.append(
                (
                    publication_directory.name,
                    {
                        "publication_id": publication_directory.name,
                        "task_id": "unknown",
                        "status": "permanent_failure",
                        "blocker_reason": "publication_integrity_failed",
                    },
                )
            )
            continue
        if (
            publication["milestone"] != "request_ready"
            or publication["blocker"] is not None
            or publication["adapter"] != adapter.adapter_id
        ):
            continue
        try:
            request, request_bytes, allow_post = _load_fixed_request(
                publication_directory, publication, adapter
            )
            attempt_directory = publication_directory / "attempts" / run_id
            write_immutable_bytes(attempt_directory / "request.json", request_bytes)
        except (WorkflowError, SchemaValidationError, OSError) as error:
            integrity_error = PublicationError(
                PublicationBlockerKind.PERMANENT_FAILURE,
                "publication_integrity_failed",
                f"Durable publication evidence failed integrity validation: {error}",
            )
            _record_publication_error(
                publication_directory, publication, run_id, integrity_error
            )
            resumed.append((str(publication["publication_id"]), _result(publication)))
            continue
        if allow_post:
            try:
                adapter.validate_request(request)
            except PublicationError as error:
                _record_publication_error(
                    publication_directory, publication, run_id, error
                )
                resumed.append((str(publication["publication_id"]), _result(publication)))
                continue
            _write_attempt_marker(
                attempt_directory / "prepared.json",
                "prepared",
                request_bytes,
            )
            result = _execute_post_attempt(
                publication_directory,
                publication,
                run_id,
                adapter,
                request,
            )
        else:
            result = _execute_confirmation_attempt(
                publication_directory,
                publication,
                run_id,
                adapter,
                request,
            )
        resumed.append((str(publication["publication_id"]), result))
    return resumed


def _execute_post_attempt(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    adapter: PublicationAdapter,
    request: dict[str, Any],
    *,
    after_send_started: Callable[[], None] | None = None,
    after_response_received: Callable[[], None] | None = None,
) -> dict[str, Any]:
    attempt_directory = publication_directory / "attempts" / run_id
    request_bytes = _json_bytes(request)
    _write_attempt_marker(
        attempt_directory / "send-started.json",
        "send_started",
        request_bytes,
    )
    if after_send_started is not None:
        after_send_started()
    return _complete_publication_attempt(
        publication_directory,
        publication,
        run_id,
        adapter,
        request,
        adapter.publish,
        after_response_received,
    )


def _execute_confirmation_attempt(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    adapter: PublicationAdapter,
    request: dict[str, Any],
) -> dict[str, Any]:
    attempt_directory = publication_directory / "attempts" / run_id
    _write_attempt_marker(
        attempt_directory / "confirmation-started.json",
        "confirmation_started",
        _json_bytes(request),
    )
    return _complete_publication_attempt(
        publication_directory,
        publication,
        run_id,
        adapter,
        request,
        adapter.confirm,
    )


def _complete_publication_attempt(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    adapter: PublicationAdapter,
    request: dict[str, Any],
    invoke: Callable[[dict[str, Any]], object],
    after_response_received: Callable[[], None] | None = None,
) -> dict[str, Any]:
    attempt_directory = publication_directory / "attempts" / run_id
    try:
        raw_response = invoke(request)
    except PublicationError as error:
        _record_publication_error(publication_directory, publication, run_id, error)
        return _result(publication)
    if after_response_received is not None:
        after_response_received()
    raw_bytes = _json_bytes(raw_response)
    write_immutable_bytes(attempt_directory / "response-raw.json", raw_bytes)
    try:
        normalized = adapter.normalize_response(raw_response)
        validate_record("publication-response", normalized)
    except PublicationError as error:
        _record_publication_error(publication_directory, publication, run_id, error)
        return _result(publication)
    write_immutable_bytes(publication_directory / "response-raw.json", raw_bytes)
    write_immutable_bytes(
        publication_directory / "response.json", _json_bytes(normalized)
    )
    publication["external_result"] = normalized
    publication["milestone"] = "publication_confirmed"
    publication["updated_at"] = utc_now()
    _commit_publication(
        publication_directory, publication, run_id, "milestone_committed"
    )
    return _result(publication)


def _request(
    publication: dict[str, Any],
    artifact: RewriteArtifact,
    publication_fields: dict[str, Any],
    publication_body: str,
    adapter: PublicationAdapter,
    *,
    image_urls: list[str] | None = None,
    cover_image_url: str | None = None,
) -> dict[str, Any]:
    request = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": 2,
        "operation": "publish_post",
        "publication_id": publication["publication_id"],
        "slug": publication["slug"],
        "publication_fields": validate_publication_fields(publication_fields),
        "title": artifact.title,
        "body_markdown": publication_body,
        "images": list(image_urls or []),
        "cover_image": cover_image_url,
        "adapter": adapter.adapter_id,
        "destination": adapter.destination_id,
    }
    validate_record("publication-request", request)
    return request


_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]\n]*\]\(([^\s\)\n]+)\)")
_LOCAL_IMAGE_NAME_PATTERN = re.compile(
    r"source-image-(?P<position>[0-9]{3})\.(?:jpg|jpeg|png|webp|gif)\Z",
    re.IGNORECASE,
)


def _publication_body(
    artifact: RewriteArtifact,
    image_policy: str | PublicationImagePolicy,
    uploaded_images: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    policy = (
        image_policy
        if isinstance(image_policy, PublicationImagePolicy)
        else PublicationImagePolicy.parse(image_policy)
    )
    source_body = artifact.content
    if policy is PublicationImagePolicy.OMIT:
        published_body, omitted_count = _MARKDOWN_IMAGE_PATTERN.subn("", source_body)
        published_body = re.sub(r"\n{3,}", "\n\n", published_body).strip() + "\n"
    elif policy.requires_uploader:
        if uploaded_images is None:
            raise WorkflowError("Uploaded publication images are missing")
        urls = {
            str(item["source_name"]): str(item["url"])
            for item in uploaded_images
        }

        def replace_image(match: re.Match[str]) -> str:
            source = match.group(1)
            return match.group(0).replace(f"({source})", f"({urls.get(source, source)})")

        published_body = _MARKDOWN_IMAGE_PATTERN.sub(replace_image, source_body)
        omitted_count = 0
    else:
        published_body = source_body
        omitted_count = 0
    if not published_body.strip():
        raise WorkflowError("Publication body is empty after applying image policy")
    presentation: dict[str, Any] = {
        "image_policy": policy.value,
        "omitted_markdown_image_count": omitted_count,
        "source_body_sha256": hashlib.sha256(source_body.encode("utf-8")).hexdigest(),
        "published_body_sha256": hashlib.sha256(
            published_body.encode("utf-8")
        ).hexdigest(),
    }
    if policy.requires_uploader:
        if uploaded_images is None:
            raise AssertionError("Upload presentation lacks images")
        cover_source = next(
            (
                str(item["source_name"])
                for item in uploaded_images
                if item.get("is_cover") is True
            ),
            None,
        )
        cover_url = next(
            (
                str(item["url"])
                for item in uploaded_images
                if item.get("is_cover") is True
            ),
            None,
        )
        presentation.update(
            {
                "cover_image_source": cover_source,
                "cover_image_url": cover_url,
                "resolved_images": uploaded_images,
            }
        )
    return published_body, presentation


def _build_image_plan(
    task_directory: Path,
    artifact: RewriteArtifact,
    *,
    cover_image: str | None,
    destination: str,
) -> dict[str, Any]:
    referenced_names: list[str] = []
    for match in _MARKDOWN_IMAGE_PATTERN.finditer(artifact.content):
        source_name = match.group(1)
        if source_name.startswith(("http://", "https://", "/assets/")):
            continue
        if _LOCAL_IMAGE_NAME_PATTERN.fullmatch(source_name) is None:
            raise BlobUploadError(
                "publication_image_reference_invalid",
                f"Unsupported local Markdown image reference: {source_name}",
                needs_configuration=False,
            )
        if source_name not in referenced_names:
            referenced_names.append(source_name)
    if len(referenced_names) > 20:
        raise BlobUploadError(
            "publication_image_count_exceeded",
            "A publication may reference at most 20 local images",
            needs_configuration=False,
        )
    if cover_image is not None and cover_image not in referenced_names:
        raise BlobUploadError(
            "publication_cover_invalid",
            "The selected cover must be one of the referenced publication images",
            needs_configuration=False,
        )

    images: list[dict[str, Any]] = []
    for source_name in referenced_names:
        name_match = _LOCAL_IMAGE_NAME_PATTERN.fullmatch(source_name)
        if name_match is None:
            raise AssertionError("Validated image name no longer matches")
        position = int(name_match.group("position"))
        if position < 1 or position > len(artifact.images):
            raise BlobUploadError(
                "publication_image_reference_missing",
                f"Markdown image has no captured source asset: {source_name}",
                needs_configuration=False,
            )
        asset_path = artifact.images[position - 1]
        content = (task_directory / asset_path).read_bytes()
        extension, content_type = validate_image_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        images.append(
            {
                "source_name": source_name,
                "asset_path": asset_path,
                "asset_sha256": digest,
                "pathname": f"weixin-blog-publish/assets/{digest}{extension}",
                "content_type": content_type,
                "is_cover": source_name == cover_image,
            }
        )
    return {
        "image_policy": "upload",
        "destination": destination,
        "cover_image_source": cover_image,
        "images": images,
    }


def _upload_planned_images(
    task_directory: Path,
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    image_plan: dict[str, Any],
    uploader: ImageUploader,
) -> list[dict[str, Any]]:
    if image_plan.get("destination") != uploader.destination_id:
        raise WorkflowError("Image upload destination changed after planning")
    planned = image_plan.get("images")
    if not isinstance(planned, list):
        raise WorkflowError("Publication image plan is invalid")
    uploaded: list[dict[str, Any]] = []
    for item in planned:
        if not isinstance(item, dict):
            raise WorkflowError("Publication image plan item is invalid")
        source = task_directory / str(item["asset_path"])
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["asset_sha256"]:
            raise WorkflowError("Publication source image changed after planning")
        record_path = (
            publication_directory
            / "image-assets"
            / f"{item['source_name']}.json"
        )
        if record_path.exists():
            record = read_json(record_path)
            _validate_uploaded_image_record(item, record, uploader)
            record_bytes = record_path.read_bytes()
            record_hash = hashlib.sha256(record_bytes).hexdigest()
            if not _image_record_anchor_exists(
                publication_directory,
                str(item["source_name"]),
                record_hash,
            ):
                recovered = uploader.upload(
                    source,
                    pathname=str(item["pathname"]),
                    content_type=str(item["content_type"]),
                )
                recovered_record = _uploaded_image_record(item, recovered, uploader)
                if recovered_record != record:
                    raise WorkflowError(
                        "Unanchored image upload record could not be recovered exactly"
                    )
                _commit_publication(
                    publication_directory,
                    publication,
                    run_id,
                    "image_uploaded",
                    details={
                        "source_name": item["source_name"],
                        "record_sha256": record_hash,
                    },
                )
        else:
            result = uploader.upload(
                source,
                pathname=str(item["pathname"]),
                content_type=str(item["content_type"]),
            )
            record = _uploaded_image_record(item, result, uploader)
            record_bytes = _json_bytes(record)
            write_immutable_bytes(record_path, record_bytes)
            _commit_publication(
                publication_directory,
                publication,
                run_id,
                "image_uploaded",
                details={
                    "source_name": item["source_name"],
                    "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
                },
            )
        uploaded.append(record)
    return uploaded


def _validate_uploaded_image_record(
    planned: dict[str, Any], record: object, uploader: ImageUploader
) -> None:
    if not isinstance(record, dict):
        raise WorkflowError("Durable uploaded image record must be an object")
    expected = {
        "source_name": planned["source_name"],
        "asset_sha256": planned["asset_sha256"],
        "pathname": planned["pathname"],
        "is_cover": planned["is_cover"],
    }
    if any(record.get(field) != value for field, value in expected.items()):
        raise WorkflowError("Durable uploaded image record no longer matches its plan")
    if (
        record.get("content_type") != planned["content_type"]
        or not isinstance(record.get("url"), str)
        or not uploader.accepts_public_url(str(record["url"]))
    ):
        raise WorkflowError("Durable uploaded image record is invalid")


def _uploaded_image_record(
    planned: dict[str, Any], result: object, uploader: ImageUploader
) -> dict[str, Any]:
    pathname = getattr(result, "pathname", None)
    content_type = getattr(result, "content_type", None)
    url = getattr(result, "url", None)
    if (
        pathname != planned["pathname"]
        or content_type != planned["content_type"]
        or not isinstance(url, str)
        or not uploader.accepts_public_url(url)
    ):
        raise BlobUploadError(
            "vercel_blob_response_invalid",
            "Blob upload returned unexpected image metadata",
            needs_configuration=False,
        )
    return {
        "source_name": planned["source_name"],
        "asset_sha256": planned["asset_sha256"],
        "pathname": pathname,
        "content_type": content_type,
        "url": url,
        "is_cover": planned["is_cover"],
    }


def _image_record_anchor_exists(
    publication_directory: Path, source_name: str, record_hash: str
) -> bool:
    events_directory = publication_directory / "events"
    if not events_directory.exists():
        return False
    for event_path in events_directory.glob("*.json"):
        event = read_json(event_path)
        validate_record("publication-event", event)
        details = event.get("details")
        if (
            event.get("type") == "image_uploaded"
            and isinstance(details, dict)
            and details.get("source_name") == source_name
            and details.get("record_sha256") == record_hash
        ):
            return True
    return False


def _commit_publication(
    directory: Path,
    publication: dict[str, Any],
    run_id: str,
    event_type: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    validate_record("publication", publication)
    snapshot_path = directory / "publication.json"
    previous = read_json(snapshot_path) if snapshot_path.exists() else None
    if previous is None:
        if publication["milestone"] != "publication_created":
            raise WorkflowError("First publication state must be publication_created")
    else:
        validate_record("publication", previous)
        changed = _publication_immutable_changes(previous, publication)
        if changed:
            raise WorkflowError(f"Publication changed immutable fields: {changed}")
        previous_milestone = str(previous["milestone"])
        next_milestone = str(publication["milestone"])
        if previous_milestone != next_milestone:
            transitions = publication_allowed_transitions()
            if next_milestone not in transitions[previous_milestone]:
                raise WorkflowError(
                    f"Illegal publication transition: {previous_milestone} -> {next_milestone}"
                )
    events = directory / "events"
    sequence = len(list(events.glob("*.json"))) + 1 if events.exists() else 1
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": new_id("event"),
        "sequence": sequence,
        "publication_id": publication["publication_id"],
        "run_id": run_id,
        "occurred_at": utc_now(),
        "type": event_type,
        "milestone": publication["milestone"],
        "details": details or {},
        "state_after": deepcopy(publication),
    }
    validate_record("publication-event", event)
    write_json(events / f"{sequence:06d}-{event['event_id']}.json", event)
    save_record("publication", snapshot_path, publication)


def validate_publication_history(directory: Path) -> dict[str, Any]:
    publication = read_json(directory / "publication.json")
    validate_record("publication", publication)
    latest: dict[str, Any] | None = None
    events = sorted((directory / "events").glob("*.json"))
    for expected_sequence, path in enumerate(events, start=1):
        event = read_json(path)
        validate_record("publication-event", event)
        if event["sequence"] != expected_sequence:
            raise WorkflowError(
                f"Publication event sequence is not contiguous at {path}"
            )
        if event["publication_id"] != directory.name:
            raise WorkflowError(
                f"Publication event {path} belongs to another publication"
            )
        if event["type"] == "image_uploaded":
            details = event["details"]
            source_name = details.get("source_name")
            record_sha256 = details.get("record_sha256")
            if not isinstance(source_name, str) or not isinstance(record_sha256, str):
                raise WorkflowError("Image upload event lacks its record identity")
            record_path = directory / "image-assets" / f"{source_name}.json"
            if (
                not record_path.exists()
                or hashlib.sha256(record_path.read_bytes()).hexdigest()
                != record_sha256
            ):
                raise WorkflowError("Image upload event record hash does not match")
        state = event["state_after"]
        if latest is not None:
            changed = _publication_immutable_changes(latest, state)
            if changed:
                raise WorkflowError(
                    f"Publication event changed immutable fields: {changed}"
                )
            previous_milestone = latest["milestone"]
            next_milestone = state["milestone"]
            allowed = set(publication_allowed_transitions()[previous_milestone])
            allowed.add(previous_milestone)
            if next_milestone not in allowed:
                raise WorkflowError(
                    f"Illegal publication event transition: {previous_milestone} -> {next_milestone}"
                )
        latest = state
    if latest is None or latest != publication:
        raise WorkflowError(
            f"Publication snapshot does not match its event history: {directory}"
        )
    return publication


def _publication_immutable_changes(
    previous: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    immutable_fields = (
        "publication_id",
        "created_in_run",
        "created_at",
        "task_id",
        "rewrite_commit_sha256",
        "target_id",
        "slug",
        "adapter",
    )
    changed = [
        field for field in immutable_fields if previous[field] != current[field]
    ]
    if previous.get("destination") != current.get("destination"):
        changed.append("destination")
    if previous.get("image_plan") != current.get("image_plan"):
        changed.append("image_plan")
    presentation_changed = previous.get("presentation") != current.get(
        "presentation"
    )
    presentation_resolved = (
        previous.get("presentation") is None
        and isinstance(current.get("presentation"), dict)
        and previous.get("milestone") == "publication_created"
        and current.get("milestone") == "publication_created"
        and isinstance(previous.get("image_plan"), dict)
    )
    if presentation_changed and not presentation_resolved:
        changed.append("presentation")
    return changed


def _result(publication: dict[str, Any]) -> dict[str, Any]:
    result = {
        "publication_id": publication["publication_id"],
        "task_id": publication["task_id"],
        "status": publication["milestone"],
    }
    if publication["blocker"] is not None:
        result["status"] = publication["blocker"]["kind"]
        result["blocker_reason"] = publication["blocker"]["error_code"]
    if publication["external_result"] is not None:
        result["public_url"] = publication["external_result"]["public_url"]
    return result


def _block(
    directory: Path,
    publication: dict[str, Any],
    run_id: str,
    error: PublicationError,
) -> None:
    publication["blocker"] = {
        "kind": error.blocker_kind.value,
        "error_code": error.code,
        "message": str(error),
    }
    publication["updated_at"] = utc_now()
    _commit_publication(directory, publication, run_id, "blocked")


def _record_publication_error(
    publication_directory: Path,
    publication: dict[str, Any],
    run_id: str,
    error: PublicationError,
) -> None:
    attempt_directory = publication_directory / "attempts" / run_id
    _write_raw_error_response(attempt_directory, error)
    _write_error(attempt_directory, error)
    _block(publication_directory, publication, run_id, error)


def _write_attempt_marker(path: Path, phase: str, request_bytes: bytes) -> None:
    marker = {
        "schema_version": 1,
        "phase": phase,
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
    }
    validate_record("publication-attempt-marker", marker)
    write_immutable_bytes(
        path,
        _json_bytes(marker),
    )


def _validate_request_identity(
    publication_directory: Path,
    publication: dict[str, Any],
    request: dict[str, Any],
    adapter: PublicationAdapter,
) -> None:
    expected = {
        "publication_id": publication["publication_id"],
        "slug": publication["slug"],
        "adapter": publication["adapter"],
    }
    observed = {field: request.get(field) for field in expected}
    if observed != expected:
        raise WorkflowError("Publication request does not match its durable identity")
    destination = request.get("destination")
    if not isinstance(destination, str):
        raise WorkflowError("Publication request lacks its fixed destination")
    if destination != adapter.destination_id:
        raise WorkflowError("Publication request destination does not match the adapter")
    repository = publication_directory.parents[1]
    task_directory = repository / "tasks" / str(publication["task_id"])
    task = load_record("task", task_directory / "task.json")
    if (
        task["task_id"] != publication["task_id"]
        or task["target_id"] != publication["target_id"]
        or task["milestone"] != "rewrite_artifact_ready"
        or task["blocker"] is not None
    ):
        raise WorkflowError("Publication no longer matches its content task")
    commit_bytes = (task_directory / "rewrite" / "commit.json").read_bytes()
    if hashlib.sha256(commit_bytes).hexdigest() != publication["rewrite_commit_sha256"]:
        raise WorkflowError("Publication rewrite commit hash no longer matches")
    artifact = load_rewrite_artifact(
        task_directory, str(publication["target_id"]), task["requirements"]
    )
    presentation = publication.get("presentation")
    if presentation is None:
        expected_body = artifact.content
        expected_images: list[str] = []
        expected_cover: str | None = None
    else:
        if not isinstance(presentation, dict):
            raise WorkflowError("Publication presentation is invalid")
        policy = str(presentation.get("image_policy"))
        uploaded_images = (
            presentation.get("resolved_images") if policy == "upload" else None
        )
        if uploaded_images is not None and not isinstance(uploaded_images, list):
            raise WorkflowError("Publication resolved images are invalid")
        expected_body, expected_presentation = _publication_body(
            artifact,
            policy,
            uploaded_images,
        )
        if presentation != expected_presentation:
            raise WorkflowError(
                "Publication presentation no longer matches its rewrite artifact"
            )
        expected_images = (
            [str(item["url"]) for item in uploaded_images]
            if isinstance(uploaded_images, list)
            else []
        )
        expected_cover_value = presentation.get("cover_image_url")
        expected_cover = (
            str(expected_cover_value)
            if isinstance(expected_cover_value, str)
            else None
        )
    if (
        request.get("publication_fields")
        != validate_publication_fields(task.get("publication_fields"))
        or request.get("title") != artifact.title
        or request.get("body_markdown") != expected_body
        or request.get("images") != expected_images
        or request.get("cover_image") != expected_cover
    ):
        raise WorkflowError("Publication request no longer matches its rewrite artifact")


def _load_fixed_request(
    publication_directory: Path,
    publication: dict[str, Any],
    adapter: PublicationAdapter,
) -> tuple[dict[str, Any], bytes, bool]:
    request_path = publication_directory / "request.json"
    request_bytes = request_path.read_bytes()
    request = read_json(request_path)
    validate_record("publication-request", request)
    _validate_request_identity(publication_directory, publication, request, adapter)
    attempts_directory = publication_directory / "attempts"
    for attempt_directory in attempts_directory.iterdir():
        if not attempt_directory.is_dir():
            continue
        attempt_request = attempt_directory / "request.json"
        if attempt_request.exists() and attempt_request.read_bytes() != request_bytes:
            raise WorkflowError("Publication attempt request differs from fixed request")
    prepared = _attempt_marker_exists(
        attempts_directory, "prepared.json", "prepared", request_bytes
    )
    send_started = _attempt_marker_exists(
        attempts_directory, "send-started.json", "send_started", request_bytes
    )
    return (
        request,
        request_bytes,
        bool(prepared and not send_started),
    )


def _attempt_marker_exists(
    attempts_directory: Path,
    filename: str,
    expected_phase: str,
    request_bytes: bytes,
) -> bool:
    found = False
    expected_hash = hashlib.sha256(request_bytes).hexdigest()
    for attempt_directory in attempts_directory.iterdir():
        if not attempt_directory.is_dir():
            continue
        marker_path = attempt_directory / filename
        if not marker_path.exists():
            continue
        marker = read_json(marker_path)
        validate_record("publication-attempt-marker", marker)
        if (
            marker["phase"] != expected_phase
            or marker["request_sha256"] != expected_hash
        ):
            raise WorkflowError("Publication attempt marker failed integrity validation")
        found = True
    return found


def _write_error(directory: Path, error: PublicationError) -> None:
    write_immutable_bytes(
        directory / "error.json",
        _json_bytes(
            {
                "kind": error.blocker_kind.value,
                "error_code": error.code,
                "message": str(error),
            }
        ),
    )


def _write_raw_error_response(directory: Path, error: PublicationError) -> None:
    if error.raw_response is None:
        return
    write_immutable_bytes(
        directory / "response-raw.json", _json_bytes(error.raw_response)
    )


def _slug(publication_id: str) -> str:
    return publication_id.replace("_", "-")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
