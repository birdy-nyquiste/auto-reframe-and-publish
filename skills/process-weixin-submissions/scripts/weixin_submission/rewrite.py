from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .schema_validation import SchemaValidationError, validate_record
from .state import load_record
from .storage import WorkflowError, write_immutable_bytes
from .submission import (
    SCHEMA_VERSION,
    StructuredSource,
    Submission,
    require_string,
)


ARTIFACT_VERSION = 1
GENERATOR = "scripted_agent_fixture_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "docs" / "content-rewrite-policy.md"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompts" / "default-content-rewrite.md"
MANIFEST_SCHEMA_PATH = SKILL_ROOT / "schemas" / "rewrite-manifest.schema.json"
REWRITE_COMMIT_PATH = "rewrite/commit.json"


class ScriptedRewriteOutcome(str, Enum):
    SUCCESS = "success"
    GENERATION_FAILURE = "generation_failure"
    VALIDATION_FAILURE = "validation_failure"
    CAPABILITY_VIOLATION = "capability_violation"


@dataclass(frozen=True)
class RewriteArtifact:
    title: str
    content: str
    target_id: str
    images: tuple[str, ...]


@dataclass(frozen=True)
class AgentRewriteOutput:
    """Data-only output supplied by a content-generation adapter."""

    content: str
    manifest: dict[str, Any]


@dataclass(frozen=True)
class AgentSourceImage:
    """One explicitly permitted, integrity-checked image supplied as data."""

    asset_path: str
    asset_sha256: str
    content: bytes


class RewriteGenerator(Protocol):
    """Content-only handoff implemented by a running Agent or a test fixture."""

    @property
    def generator_id(self) -> str:
        """Return the stable generator identity recorded in the manifest."""
        ...

    def generate(
        self,
        rewrite_input: dict[str, Any],
        source: StructuredSource,
        source_images: list[dict[str, str]],
        permitted_images: tuple[AgentSourceImage, ...],
        resource_records: dict[str, dict[str, str]],
        input_sha256: str,
    ) -> AgentRewriteOutput:
        """Return Markdown and its manifest without performing external actions."""


@dataclass(frozen=True)
class ScriptedAgentGenerator:
    """Data-only core-validation fixture for the live Agent callback seam."""

    outcome: ScriptedRewriteOutcome = ScriptedRewriteOutcome.SUCCESS
    generator_id: str = GENERATOR

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ScriptedRewriteOutcome):
            raise WorkflowError(
                f"Unsupported scripted rewrite outcome: {self.outcome}"
            )

    def generate(
        self,
        rewrite_input: dict[str, Any],
        source: StructuredSource,
        source_images: list[dict[str, str]],
        permitted_images: tuple[AgentSourceImage, ...],
        resource_records: dict[str, dict[str, str]],
        input_sha256: str,
    ) -> AgentRewriteOutput:
        return _scripted_agent_generate(
            rewrite_input,
            source,
            source_images,
            permitted_images,
            resource_records,
            input_sha256,
            self.outcome,
        )


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
    generator: RewriteGenerator,
) -> RewriteArtifact:
    if not generator.generator_id:
        raise WorkflowError("Rewrite generator must declare an identifier")
    manifest_path = task_directory / "rewrite" / "manifest.json"
    commit_path = task_directory / REWRITE_COMMIT_PATH
    if commit_path.exists():
        return load_rewrite_artifact(
            task_directory, submission.target_id, submission.requirements
        )

    source_path = task_directory / "sources" / "article.json"
    source_images = _source_images(source_path)
    permitted_images = tuple(
        AgentSourceImage(
            image["asset_path"],
            image["asset_sha256"],
            _read_bytes(task_directory / image["asset_path"]),
        )
        for image in source_images
    )
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

    if (
        isinstance(generator, ScriptedAgentGenerator)
        and generator.outcome is ScriptedRewriteOutcome.GENERATION_FAILURE
    ):
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
            None,
        )
        raise rejection

    output = generator.generate(
        rewrite_input,
        source,
        source_images,
        permitted_images,
        resource_records,
        _sha256(rewrite_input_bytes),
    )
    content = output.content
    content_bytes = content.encode("utf-8")
    candidate_relative_path = f"rewrite/attempts/{run_id}/candidate.md"
    candidate_record = {
        "path": candidate_relative_path,
        "sha256": _sha256(content_bytes),
    }
    write_immutable_bytes(task_directory / candidate_relative_path, content_bytes)
    candidate_manifest_path = (
        task_directory
        / "rewrite"
        / "attempts"
        / run_id
        / "candidate-manifest.json"
    )
    candidate_manifest_bytes = _json_bytes(output.manifest)
    write_immutable_bytes(candidate_manifest_path, candidate_manifest_bytes)
    candidate_manifest_record = {
        "path": candidate_manifest_path.relative_to(task_directory).as_posix(),
        "sha256": _sha256(candidate_manifest_bytes),
    }
    try:
        _validate_markdown(content)
        validate_record("rewrite-manifest", output.manifest)
        _validate_agent_manifest(
            output.manifest,
            rewrite_input,
            content_bytes,
            generator.generator_id,
        )
    except (SchemaValidationError, WorkflowError) as error:
        rejection = RewriteRejected(
            "rewrite_candidate_invalid",
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
            candidate_manifest_record,
        )
        raise rejection from error
    write_immutable_bytes(task_directory / "rewrite" / "content.md", content_bytes)
    manifest_bytes = candidate_manifest_bytes
    write_immutable_bytes(manifest_path, manifest_bytes)
    commit = {
        "schema_version": SCHEMA_VERSION,
        "commit_version": 1,
        "artifact_kind": "validated_rewrite_commit",
        "manifest_path": "rewrite/manifest.json",
        "manifest_sha256": _sha256(manifest_bytes),
    }
    validate_record("rewrite-commit", commit)
    write_immutable_bytes(commit_path, _json_bytes(commit))
    return load_rewrite_artifact(
        task_directory, submission.target_id, submission.requirements
    )


def load_rewrite_artifact(
    task_directory: Path,
    expected_target_id: str,
    expected_requirements: str | None = None,
) -> RewriteArtifact:
    manifest_path = task_directory / "rewrite" / "manifest.json"
    manifest_bytes = _read_bytes(manifest_path)
    commit = load_record("rewrite-commit", task_directory / REWRITE_COMMIT_PATH)
    _require_hash(
        manifest_bytes,
        commit.get("manifest_sha256"),
        manifest_path,
    )
    manifest = load_record(
        "rewrite-manifest", manifest_path
    )
    controls = manifest["trusted_controls"]
    if not isinstance(controls, dict) or controls.get("target_id") != expected_target_id:
        raise WorkflowError("Rewrite artifact target does not match trusted task control")
    expected_mode = "custom" if expected_requirements is not None else "default"
    expected_requirements_hash = (
        _sha256(expected_requirements.encode("utf-8"))
        if expected_requirements is not None
        else None
    )
    if (
        controls.get("requirements_mode") != expected_mode
        or controls.get("requirements_sha256") != expected_requirements_hash
    ):
        raise WorkflowError(
            "Rewrite artifact requirements do not match trusted task control"
        )
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
    source_path = task_directory / require_string(
        source_record.get("path"), "rewrite source path"
    )
    source_bytes = _read_bytes(source_path)
    _require_hash(source_bytes, source_record.get("sha256"), source_path)
    source = load_record("structured-source", source_path)

    resources = manifest.get("resources")
    if not isinstance(resources, dict):
        raise WorkflowError("Rewrite artifact resources are invalid")
    expected_resources = {
        "policy": POLICY_PATH,
        "default_prompt": DEFAULT_PROMPT_PATH,
        "schema": MANIFEST_SCHEMA_PATH,
    }
    for name, expected_path in expected_resources.items():
        resource = resources.get(name)
        expected_record = _resource_record(expected_path)
        if resource != expected_record:
            raise WorkflowError(f"Rewrite artifact {name} resource does not match")

    input_hash = require_string(
        manifest.get("generation_input_sha256"), "rewrite generation input sha256"
    )
    matching_inputs = [
        path
        for path in (task_directory / "rewrite" / "attempts").glob("*/input.json")
        if _sha256(_read_bytes(path)) == input_hash
    ]
    if not matching_inputs:
        raise WorkflowError("Rewrite artifact generation input is not anchored")
    rewrite_input = load_record("rewrite-input", matching_inputs[0])
    if (
        rewrite_input.get("trusted_controls")
        != {
            "target_id": expected_target_id,
            "requirements_mode": expected_mode,
            "requirements": expected_requirements,
        }
        or rewrite_input.get("untrusted_source")
        != {
            "path": "sources/article.json",
            "sha256": source_record.get("sha256"),
            "images": source_record.get("images"),
        }
        or rewrite_input.get("resources") != resources
    ):
        raise WorkflowError("Rewrite artifact generation input does not match manifest")

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
    source_images = source.get("images")
    if not isinstance(source_images, list):
        raise WorkflowError("Structured source images must be a list")
    expected_source_images = [
        {
            "asset_path": image.get("asset_path"),
            "asset_sha256": image.get("asset_sha256"),
        }
        for image in source_images
        if isinstance(image, dict)
    ]
    if image_records != expected_source_images:
        raise WorkflowError("Rewrite artifact images do not match structured source")
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


def _scripted_agent_generate(
    rewrite_input: dict[str, Any],
    source: StructuredSource,
    source_images: list[dict[str, str]],
    permitted_images: tuple[AgentSourceImage, ...],
    resource_records: dict[str, dict[str, str]],
    input_sha256: str,
    outcome: ScriptedRewriteOutcome,
) -> AgentRewriteOutput:
    """Validation fixture for the Agent handoff; it has no action capabilities."""

    content = (
        "candidate without an H1 title"
        if outcome is ScriptedRewriteOutcome.VALIDATION_FAILURE
        else _build_scripted_placeholder(source)
    )
    controls = rewrite_input["trusted_controls"]
    if not isinstance(controls, dict):
        raise WorkflowError("Rewrite input trusted controls are invalid")
    requirements = controls.get("requirements")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_version": ARTIFACT_VERSION,
        "artifact_kind": "validated_rewrite",
        "generator": GENERATOR,
        "generation_input_sha256": input_sha256,
        "title": source.title,
        "content": {
            "path": "rewrite/content.md",
            "format": "markdown",
            "sha256": _sha256(content.encode("utf-8")),
        },
        "source": {
            "path": "sources/article.json",
            "sha256": rewrite_input["untrusted_source"]["sha256"],
            "images": source_images,
        },
        "trusted_controls": {
            "target_id": controls.get("target_id"),
            "requirements_mode": controls.get("requirements_mode"),
            "requirements_sha256": (
                _sha256(requirements.encode("utf-8"))
                if isinstance(requirements, str)
                else None
            ),
        },
        "resources": resource_records,
        "security": {
            "source_trust": "untrusted",
            "allowed_effect": "content_only",
        },
    }
    injection_channels_observed = (
        "file://" in source.body
        and "touch " in source.body
        and "二维码" in source.body
        and "模拟外部响应" in source.body
        and any(
            b"IMAGE_INJECTION_PUBLISH" in image.content
            for image in permitted_images
        )
    )
    if (
        outcome is ScriptedRewriteOutcome.CAPABILITY_VIOLATION
        and injection_channels_observed
    ):
        manifest["trusted_controls"]["target_id"] = "attacker"
    return AgentRewriteOutput(content, manifest)


def _validate_agent_manifest(
    manifest: dict[str, Any],
    rewrite_input: dict[str, Any],
    content_bytes: bytes,
    expected_generator_id: str,
) -> None:
    controls = rewrite_input["trusted_controls"]
    requirements = controls["requirements"]
    expected_controls = {
        "target_id": controls["target_id"],
        "requirements_mode": controls["requirements_mode"],
        "requirements_sha256": (
            _sha256(requirements.encode("utf-8"))
            if isinstance(requirements, str)
            else None
        ),
    }
    expected_content = {
        "path": "rewrite/content.md",
        "format": "markdown",
        "sha256": _sha256(content_bytes),
    }
    if manifest.get("trusted_controls") != expected_controls:
        raise WorkflowError("Agent manifest changed trusted controls")
    if manifest.get("generator") != expected_generator_id:
        raise WorkflowError("Agent manifest changed its generator identity")
    if manifest.get("content") != expected_content:
        raise WorkflowError("Agent manifest does not describe its Markdown output")
    if manifest.get("source") != rewrite_input["untrusted_source"]:
        raise WorkflowError("Agent manifest changed the untrusted source record")
    if manifest.get("resources") != rewrite_input["resources"]:
        raise WorkflowError("Agent manifest changed the trusted resource records")
    if manifest.get("generation_input_sha256") != _sha256(
        _json_bytes(rewrite_input)
    ):
        raise WorkflowError("Agent manifest does not reference its generation input")
    if manifest.get("security") != {
        "source_trust": "untrusted",
        "allowed_effect": "content_only",
    }:
        raise WorkflowError("Agent manifest changed the security boundary")


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
    candidate_manifest: dict[str, str] | None,
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
        "candidate_manifest": candidate_manifest,
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
