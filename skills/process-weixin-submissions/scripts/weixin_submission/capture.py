from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from .schema_validation import validate_record
from .state import load_record, save_record
from .storage import WorkflowError, write_immutable_bytes
from .submission import SCHEMA_VERSION, StructuredSource, Submission, require_string


CAPTURE_VERSION = 1
MIN_TEXT_CHARACTERS_WITH_EMBEDDED_MEDIA = 20


class CaptureRejected(WorkflowError):
    def __init__(
        self, code: str, message: str, *, category: str, retryable: bool
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.retryable = retryable


def capture_raw_evidence(
    task_directory: Path, submission: Submission, attempt_id: str
) -> dict[str, Any]:
    rejection = _capture_rejection(submission)
    capture_root = (
        "raw/capture"
        if rejection is None
        else f"raw/capture-attempts/{attempt_id}"
    )
    body_bytes = submission.capture.clipboard_text.encode("utf-8")
    body_path = f"{capture_root}/clipboard.txt"
    image_occurrences, embedded_media, warnings, evidence_files = _capture_media(
        capture_root, submission.capture.media
    )
    complete = (
        submission.capture.article_end_observed
        and submission.capture.all_static_images_captured
    )
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "capture_version": CAPTURE_VERSION,
        "adapter": "scripted_capture",
        "title": submission.title,
        "source_url": submission.capture.source_url,
        "body": {
            "method": "copy_paste",
            "path": body_path,
            "sha256": _sha256(body_bytes),
            "character_count": len(submission.capture.clipboard_text),
        },
        "article_end": {
            "observed": submission.capture.article_end_observed,
            "method": "scripted_fixture",
        },
        "image_occurrences": image_occurrences,
        "embedded_media": embedded_media,
        "warnings": warnings,
        "completeness": {
            "body_text": True,
            "article_end_observed": submission.capture.article_end_observed,
            "all_static_images_captured": (
                submission.capture.all_static_images_captured
            ),
            "complete": complete,
        },
    }
    validate_record("capture-manifest", manifest)
    for evidence_path, evidence_bytes in evidence_files:
        write_immutable_bytes(task_directory / evidence_path, evidence_bytes)
    write_immutable_bytes(task_directory / body_path, body_bytes)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    write_immutable_bytes(
        task_directory / capture_root / "manifest.json", manifest_bytes
    )
    if rejection is not None:
        raise rejection
    return manifest


def _capture_rejection(submission: Submission) -> CaptureRejected | None:
    if not submission.capture.article_end_observed:
        return CaptureRejected(
            "article_end_not_observed",
            "Article end was not observed, so raw capture is incomplete",
            category="capture_incomplete",
            retryable=True,
        )
    if not submission.capture.all_static_images_captured:
        return CaptureRejected(
            "static_images_incomplete",
            "Not all static image occurrences were captured",
            category="capture_incomplete",
            retryable=True,
        )
    has_embedded_media = any(
        item.get("kind") in ("video", "audio")
        for item in submission.capture.media
    )
    meaningful_characters = sum(
        not character.isspace() for character in submission.capture.clipboard_text
    )
    if (
        has_embedded_media
        and meaningful_characters < MIN_TEXT_CHARACTERS_WITH_EMBEDDED_MEDIA
    ):
        return CaptureRejected(
            "media_only_source",
            "Article depends on uncaptured audio or video and has insufficient text",
            category="source_limitation",
            retryable=False,
        )
    return None


def rebuild_structured_source(task_directory: Path) -> StructuredSource:
    manifest = load_record(
        "capture-manifest", task_directory / "raw" / "capture" / "manifest.json"
    )
    _verify_manifest_completeness(manifest)
    body_record = manifest["body"]
    if not isinstance(body_record, dict):
        raise WorkflowError("Capture manifest body is invalid")
    body_relative_path = require_string(body_record.get("path"), "body path")
    if body_relative_path != "raw/capture/clipboard.txt":
        raise WorkflowError("Capture manifest body path is not canonical")
    body_path = task_directory / body_relative_path
    body_bytes = _read_evidence(body_path)
    _require_hash(body_bytes, body_record.get("sha256"), body_path)
    try:
        body = body_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkflowError("Captured clipboard text is not UTF-8") from error
    if body_record.get("character_count") != len(body):
        raise WorkflowError("Captured clipboard character count is inconsistent")
    source_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "title": manifest["title"],
        "body": body,
        "source_url": manifest["source_url"],
        "images": _structured_images(task_directory, manifest),
        "warnings": list(manifest["warnings"]),
        "media_limitations": [
            str(item["warning"])
            for item in manifest["embedded_media"]
            if isinstance(item, dict)
        ],
    }
    save_record(
        "structured-source", task_directory / "sources" / "article.json", source_record
    )
    return load_structured_source(task_directory / "sources" / "article.json")


def load_structured_source(path: Path) -> StructuredSource:
    record = load_record("structured-source", path)
    images = record["images"]
    if not isinstance(images, list):
        raise WorkflowError("Structured source images must be a list")
    image_paths = tuple(
        require_string(image.get("asset_path"), "structured image asset_path")
        for image in images
        if isinstance(image, dict)
    )
    warnings = record["warnings"]
    limitations = record["media_limitations"]
    if not isinstance(warnings, list) or not isinstance(limitations, list):
        raise WorkflowError("Structured source warnings must be arrays")
    return StructuredSource(
        require_string(record.get("title"), "structured source title"),
        require_string(record.get("body"), "structured source body"),
        record.get("source_url") if isinstance(record.get("source_url"), str) else None,
        image_paths,
        tuple(str(item) for item in warnings),
        tuple(str(item) for item in limitations),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_hash(value: bytes, expected: object, path: Path) -> None:
    actual = _sha256(value)
    if not isinstance(expected, str) or actual != expected:
        raise WorkflowError(f"Capture evidence hash mismatch: {path}")


def _read_evidence(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise WorkflowError(f"Cannot read capture evidence: {path}") from error


def _verify_manifest_completeness(manifest: dict[str, Any]) -> None:
    completeness = manifest.get("completeness")
    article_end = manifest.get("article_end")
    if not isinstance(completeness, dict) or not isinstance(article_end, dict):
        raise WorkflowError("Capture completeness metadata is invalid")
    expected_complete = (
        completeness.get("body_text") is True
        and completeness.get("all_static_images_captured") is True
        and article_end.get("observed") is True
    )
    if completeness.get("article_end_observed") != article_end.get("observed"):
        raise WorkflowError("Capture article-end metadata is inconsistent")
    if completeness.get("complete") != expected_complete:
        raise WorkflowError("Capture completeness metadata is inconsistent")
    if not expected_complete:
        raise WorkflowError("Raw capture evidence is incomplete")


def _capture_media(
    capture_root: str, media: tuple[dict[str, Any], ...]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    list[tuple[str, bytes]],
]:
    occurrences: list[dict[str, Any]] = []
    embedded_media: list[dict[str, Any]] = []
    warnings: list[str] = []
    evidence_files: list[tuple[str, bytes]] = []
    for article_position, item in enumerate(media, start=1):
        kind = item.get("kind")
        if kind in ("video", "audio"):
            warning = (
                f"Embedded {kind} at article position {article_position} "
                "was not downloaded or transcribed"
            )
            embedded_media.append(
                {
                    "article_position": article_position,
                    "kind": kind,
                    "downloaded": False,
                    "transcribed": False,
                    "warning": warning,
                }
            )
            warnings.append(warning)
            continue
        if kind == "gif":
            mime_type = require_string(
                item.get("static_frame_mime_type"), "GIF static frame mime_type"
            )
            image_bytes = _decode_base64(
                item.get("static_frame_bytes_base64"), "GIF static frame bytes"
            )
            capture_method = "static_frame"
            degradation: str | None = "animation_removed"
            viewport_evidence: dict[str, Any] | None = None
            warning = (
                f"GIF animation at article position {article_position} "
                "was reduced to a static frame"
            )
            warnings.append(warning)
        elif kind == "image":
            capture_method = require_string(
                item.get("capture_method"), "image capture_method"
            )
            mime_type = require_string(item.get("mime_type"), "image mime_type")
            image_bytes = _decode_base64(item.get("bytes_base64"), "image bytes")
            degradation = None
            viewport_evidence = None
        else:
            raise WorkflowError(f"Unsupported scripted media kind: {kind}")
        _require_static_mime(mime_type)
        digest = _sha256(image_bytes)
        asset_path = f"{capture_root}/assets/{digest}"
        evidence_files.append((asset_path, image_bytes))
        if capture_method in ("original_bytes", "static_frame"):
            pass
        elif capture_method == "viewport_crop":
            viewport_mime_type = require_string(
                item.get("viewport_mime_type"), "viewport mime_type"
            )
            viewport_bytes = _decode_base64(
                item.get("viewport_bytes_base64"), "viewport bytes"
            )
            _require_static_mime(viewport_mime_type)
            viewport_digest = _sha256(viewport_bytes)
            viewport_path = f"{capture_root}/viewports/{viewport_digest}"
            evidence_files.append((viewport_path, viewport_bytes))
            degradation = "screenshot_crop"
            viewport_evidence = {
                "path": viewport_path,
                "sha256": viewport_digest,
                "crop": _crop_rectangle(item.get("crop")),
            }
        else:
            raise WorkflowError(f"Unsupported image capture method: {capture_method}")
        occurrences.append(
            {
                "position": len(occurrences) + 1,
                "article_position": article_position,
                "source_kind": kind,
                "asset_path": asset_path,
                "asset_sha256": digest,
                "mime_type": mime_type,
                "capture_method": capture_method,
                "degradation": degradation,
                "viewport_evidence": viewport_evidence,
            }
        )
    return occurrences, embedded_media, warnings, evidence_files


def _structured_images(
    task_directory: Path, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    occurrences = manifest["image_occurrences"]
    if not isinstance(occurrences, list):
        raise WorkflowError("Capture image occurrences must be a list")
    result: list[dict[str, Any]] = []
    for expected_position, occurrence in enumerate(occurrences, start=1):
        if not isinstance(occurrence, dict):
            raise WorkflowError("Capture image occurrence must be an object")
        if occurrence.get("position") != expected_position:
            raise WorkflowError("Capture image occurrence order is not contiguous")
        asset_path = require_string(occurrence.get("asset_path"), "image asset path")
        asset_sha256 = require_string(
            occurrence.get("asset_sha256"), "image asset sha256"
        )
        if asset_path != f"raw/capture/assets/{asset_sha256}":
            raise WorkflowError("Capture image asset path is not canonical")
        asset = task_directory / asset_path
        _require_hash(_read_evidence(asset), asset_sha256, asset)
        _verify_capture_method_evidence(task_directory, occurrence)
        result.append(
            {
                "position": expected_position,
                "article_position": occurrence["article_position"],
                "source_kind": occurrence["source_kind"],
                "asset_path": asset_path,
                "asset_sha256": occurrence["asset_sha256"],
                "mime_type": occurrence["mime_type"],
                "capture_method": occurrence["capture_method"],
                "degradation": occurrence["degradation"],
            }
        )
    return result


def _verify_capture_method_evidence(
    task_directory: Path, occurrence: dict[str, Any]
) -> None:
    capture_method = occurrence.get("capture_method")
    source_kind = occurrence.get("source_kind")
    degradation = occurrence.get("degradation")
    viewport = occurrence.get("viewport_evidence")
    if capture_method == "viewport_crop":
        if source_kind != "image" or degradation != "screenshot_crop":
            raise WorkflowError("Viewport capture metadata is inconsistent")
        if not isinstance(viewport, dict):
            raise WorkflowError("Viewport capture is missing original evidence")
        viewport_path = require_string(viewport.get("path"), "viewport evidence path")
        viewport_sha256 = require_string(
            viewport.get("sha256"), "viewport evidence sha256"
        )
        if viewport_path != f"raw/capture/viewports/{viewport_sha256}":
            raise WorkflowError("Viewport evidence path is not canonical")
        evidence = task_directory / viewport_path
        _require_hash(_read_evidence(evidence), viewport_sha256, evidence)
        return
    if viewport is not None:
        raise WorkflowError("Non-viewport capture must not have viewport evidence")
    if capture_method == "original_bytes":
        if source_kind != "image" or degradation is not None:
            raise WorkflowError("Original image capture metadata is inconsistent")
        return
    if capture_method == "static_frame":
        if source_kind != "gif" or degradation != "animation_removed":
            raise WorkflowError("GIF static frame metadata is inconsistent")
        return
    raise WorkflowError(f"Unsupported stored capture method: {capture_method}")


def _decode_base64(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise WorkflowError(f"{field} must be base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise WorkflowError(f"{field} is invalid base64") from error
    if not decoded:
        raise WorkflowError(f"{field} must not be empty")
    return decoded


def _require_static_mime(mime_type: str) -> None:
    if mime_type not in ("image/png", "image/jpeg", "image/webp"):
        raise WorkflowError(f"Unsupported static image MIME type: {mime_type}")


def _crop_rectangle(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise WorkflowError("viewport crop must be an object")
    result: dict[str, int] = {}
    for field in ("x", "y", "width", "height"):
        coordinate = value.get(field)
        minimum = 0 if field in ("x", "y") else 1
        if (
            not isinstance(coordinate, int)
            or isinstance(coordinate, bool)
            or coordinate < minimum
        ):
            raise WorkflowError(f"viewport crop {field} is invalid")
        result[field] = coordinate
    return result
