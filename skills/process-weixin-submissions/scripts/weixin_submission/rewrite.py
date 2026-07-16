from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema_validation import validate_record
from .state import load_record
from .storage import WorkflowError, write_immutable_bytes
from .submission import (
    SCHEMA_VERSION,
    StructuredSource,
    Submission,
    require_string,
)


ARTIFACT_VERSION = 1
GENERATOR = "scripted_placeholder_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "docs" / "content-rewrite-policy.md"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompts" / "default-content-rewrite.md"
MANIFEST_SCHEMA_PATH = SKILL_ROOT / "schemas" / "rewrite-manifest.schema.json"


@dataclass(frozen=True)
class RewriteArtifact:
    title: str
    content: str
    target_id: str
    images: tuple[str, ...]


class RewriteRejected(WorkflowError):
    def __init__(self, code: str, message: str, *, category: str, phase: str) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.phase = phase


def generate_validated_rewrite(
    task_directory: Path,
    submission: Submission,
    source: StructuredSource,
    run_id: str,
    scripted_outcome: str = "success",
) -> RewriteArtifact:
    manifest_path = task_directory / "rewrite" / "manifest.json"
    if manifest_path.exists():
        return load_rewrite_artifact(task_directory, submission.target_id)

    source_path = task_directory / "sources" / "article.json"
    source_images = _source_images(source_path)
    resource_records = {
        "policy": _resource_record(POLICY_PATH),
        "default_prompt": _resource_record(DEFAULT_PROMPT_PATH),
        "schema": _resource_record(MANIFEST_SCHEMA_PATH),
    }
    rewrite_input: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": 1,
        "task_id": task_directory.name,
        "trusted_controls": {
            "target_id": submission.target_id,
            "requirements_mode": (
                "custom" if submission.requirements is not None else "default"
            ),
            "requirements": submission.requirements,
        },
        "untrusted_source": {
            "path": "sources/article.json",
            "sha256": _sha256(_read_bytes(source_path)),
            "images": source_images,
        },
        "resources": resource_records,
        "security": {
            "source_trust": "untrusted",
            "allowed_effect": "content_only",
            "prohibited_actions": [
                "change_target",
                "read_local_files",
                "execute_commands",
                "expand_external_actions",
            ],
        },
    }
    validate_record("rewrite-input", rewrite_input)
    rewrite_input_bytes = _json_bytes(rewrite_input)
    write_immutable_bytes(
        task_directory / "rewrite" / "attempts" / run_id / "input.json",
        rewrite_input_bytes,
    )

    if scripted_outcome == "generation_failure":
        rejection = RewriteRejected(
            "scripted_generation_failure",
            "Scripted Agent failed before producing Markdown",
            category="rewrite_generation",
            phase="generation",
        )
        _write_attempt_failure(
            task_directory,
            run_id,
            rejection,
            _sha256(rewrite_input_bytes),
            None,
        )
        raise rejection

    content = (
        "candidate without an H1 title"
        if scripted_outcome == "validation_failure"
        else _build_scripted_placeholder(source)
    )
    content_bytes = content.encode("utf-8")
    candidate_relative_path = f"rewrite/attempts/{run_id}/candidate.md"
    candidate_record = {
        "path": candidate_relative_path,
        "sha256": _sha256(content_bytes),
    }
    write_immutable_bytes(task_directory / candidate_relative_path, content_bytes)
    try:
        _validate_markdown(content)
    except WorkflowError as error:
        rejection = RewriteRejected(
            "rewrite_markdown_invalid",
            str(error),
            category="rewrite_validation",
            phase="validation",
        )
        _write_attempt_failure(
            task_directory,
            run_id,
            rejection,
            _sha256(rewrite_input_bytes),
            candidate_record,
        )
        raise rejection from error
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_version": ARTIFACT_VERSION,
        "artifact_kind": "validated_rewrite",
        "generator": GENERATOR,
        "generation_input_sha256": _sha256(rewrite_input_bytes),
        "title": source.title,
        "content": {
            "path": "rewrite/content.md",
            "format": "markdown",
            "sha256": _sha256(content_bytes),
        },
        "source": {
            "path": "sources/article.json",
            "sha256": _sha256(_read_bytes(source_path)),
            "images": source_images,
        },
        "trusted_controls": {
            "target_id": submission.target_id,
            "requirements_mode": (
                "custom" if submission.requirements is not None else "default"
            ),
            "requirements_sha256": (
                _sha256(submission.requirements.encode("utf-8"))
                if submission.requirements is not None
                else None
            ),
        },
        "resources": resource_records,
        "security": {
            "source_trust": "untrusted",
            "allowed_effect": "content_only",
        },
    }
    validate_record("rewrite-manifest", manifest)
    write_immutable_bytes(task_directory / "rewrite" / "content.md", content_bytes)
    write_immutable_bytes(
        manifest_path,
        _json_bytes(manifest),
    )
    return load_rewrite_artifact(task_directory, submission.target_id)


def load_rewrite_artifact(
    task_directory: Path, expected_target_id: str
) -> RewriteArtifact:
    manifest = load_record(
        "rewrite-manifest", task_directory / "rewrite" / "manifest.json"
    )
    controls = manifest["trusted_controls"]
    if not isinstance(controls, dict) or controls.get("target_id") != expected_target_id:
        raise WorkflowError("Rewrite artifact target does not match trusted task control")
    content_record = manifest["content"]
    source_record = manifest["source"]
    if not isinstance(content_record, dict) or not isinstance(source_record, dict):
        raise WorkflowError("Rewrite artifact records are invalid")
    content_path = task_directory / require_string(
        content_record.get("path"), "rewrite content path"
    )
    content_bytes = _read_bytes(content_path)
    _require_hash(content_bytes, content_record.get("sha256"), content_path)
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkflowError("Rewrite content is not UTF-8") from error
    _validate_markdown(content)
    image_records = source_record.get("images")
    if not isinstance(image_records, list):
        raise WorkflowError("Rewrite artifact images must be a list")
    image_paths: list[str] = []
    for image in image_records:
        if not isinstance(image, dict):
            raise WorkflowError("Rewrite artifact image must be an object")
        asset_path = require_string(image.get("asset_path"), "rewrite image path")
        asset_sha256 = require_string(
            image.get("asset_sha256"), "rewrite image sha256"
        )
        if asset_path != f"raw/capture/assets/{asset_sha256}":
            raise WorkflowError("Rewrite image path is not canonical")
        _require_hash(
            _read_bytes(task_directory / asset_path),
            asset_sha256,
            task_directory / asset_path,
        )
        image_paths.append(asset_path)
    return RewriteArtifact(
        require_string(manifest.get("title"), "rewrite title"),
        content,
        expected_target_id,
        tuple(image_paths),
    )


def _validate_markdown(content: str) -> None:
    if not content.strip():
        raise WorkflowError("Rewrite Markdown must not be empty")
    if "\x00" in content:
        raise WorkflowError("Rewrite Markdown must not contain NUL")
    if not content.startswith("# "):
        raise WorkflowError("Rewrite Markdown must start with one H1 title")


def _build_scripted_placeholder(source: StructuredSource) -> str:
    return (
        f"# {source.title}\n\n"
        "> 这是 Ticket 05 的已验证脚本化占位产物；正式改写规则等待 Ticket 09。\n\n"
        f"## 正文\n\n{source.body}\n"
    )


def _resource_record(path: Path) -> dict[str, str]:
    try:
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError as error:
        raise WorkflowError(f"Rewrite resource is outside the project: {path}") from error
    return {"path": relative_path, "sha256": _sha256(_read_bytes(path))}


def _source_images(source_path: Path) -> list[dict[str, str]]:
    source_record = load_record("structured-source", source_path)
    images = source_record.get("images")
    if not isinstance(images, list):
        raise WorkflowError("Structured source images must be a list")
    result: list[dict[str, str]] = []
    for image in images:
        if not isinstance(image, dict):
            raise WorkflowError("Structured source image must be an object")
        result.append(
            {
                "asset_path": require_string(
                    image.get("asset_path"), "source image path"
                ),
                "asset_sha256": require_string(
                    image.get("asset_sha256"), "source image sha256"
                ),
            }
        )
    return result


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_attempt_failure(
    task_directory: Path,
    run_id: str,
    rejection: RewriteRejected,
    input_sha256: str,
    candidate: dict[str, str] | None,
) -> None:
    failure: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "attempt_version": 1,
        "task_id": task_directory.name,
        "run_id": run_id,
        "phase": rejection.phase,
        "error_category": rejection.category,
        "error_code": rejection.code,
        "message": str(rejection),
        "input_sha256": input_sha256,
        "candidate": candidate,
    }
    validate_record("rewrite-attempt-failure", failure)
    write_immutable_bytes(
        task_directory / "rewrite" / "attempts" / run_id / "failure.json",
        _json_bytes(failure),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_hash(value: bytes, expected: object, path: Path) -> None:
    if not isinstance(expected, str) or _sha256(value) != expected:
        raise WorkflowError(f"Rewrite artifact hash mismatch: {path}")


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise WorkflowError(f"Cannot read rewrite resource: {path}") from error
