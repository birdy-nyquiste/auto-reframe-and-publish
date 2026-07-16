from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/process-weixin-submissions/scripts/process_weixin_submissions.py"


def run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *(str(argument) for argument in arguments)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class DraftDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.repository = root / "task-repository"
        self.chat = root / "scripted-chat.json"
        self.fake_blog = root / "fake-blog"
        self.chat.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "conversation": "file-transfer-assistant",
                    "messages": [],
                    "arrive_after_next_marker": [],
                }
            ),
            encoding="utf-8",
        )
        initialized = run_cli(
            "initialize",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def append_submission(self) -> str:
        image_bytes = b"same-image-used-twice"
        chat = json.loads(self.chat.read_text("utf-8"))
        chat["messages"].extend(
            [
                {
                    "message_id": "delivery-header",
                    "kind": "text",
                    "text": "#投稿\n目标: opaque-author-42",
                },
                {
                    "message_id": "delivery-article",
                    "kind": "official_account_article",
                    "title": "交付契约测试",
                    "scripted_capture": {
                        "clipboard_text": "用于验证草稿交付边界的正文。",
                        "source_url": "https://example.com/delivery",
                        "article_end_observed": True,
                        "all_static_images_captured": True,
                        "media": [
                            {
                                "kind": "image",
                                "mime_type": "image/png",
                                "capture_method": "original_bytes",
                                "bytes_base64": base64.b64encode(image_bytes).decode(),
                            },
                            {
                                "kind": "image",
                                "mime_type": "image/png",
                                "capture_method": "original_bytes",
                                "bytes_base64": base64.b64encode(image_bytes).decode(),
                            },
                        ],
                    },
                },
            ]
        )
        self.chat.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return hashlib.sha256(image_bytes).hexdigest()

    def run_intake(self) -> dict[str, Any]:
        completed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return cast(dict[str, Any], json.loads(completed.stdout))

    def test_canonical_artifact_maps_target_uploads_images_and_creates_draft(
        self,
    ) -> None:
        image_sha256 = self.append_submission()

        result = self.run_intake()

        task_id = result["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        request = json.loads(
            (task_directory / "delivery" / "request.json").read_text("utf-8")
        )
        expected_asset_id = f"asset-{image_sha256}"
        self.assertEqual(request["operation"], "create_draft")
        self.assertEqual(request["idempotency_key"], task_id)
        self.assertEqual(
            request["target"],
            {
                "source_id": "opaque-author-42",
                "external_id": "fake-target:opaque-author-42",
            },
        )
        self.assertEqual(
            request["images"],
            [
                {
                    "occurrence": 1,
                    "asset_id": expected_asset_id,
                    "sha256": image_sha256,
                },
                {
                    "occurrence": 2,
                    "asset_id": expected_asset_id,
                    "sha256": image_sha256,
                },
            ],
        )
        uploads = list((self.fake_blog / "uploads").glob("*.json"))
        self.assertEqual(len(uploads), 1)
        upload = json.loads(uploads[0].read_text("utf-8"))
        self.assertEqual(upload["asset_id"], expected_asset_id)
        self.assertEqual(upload["sha256"], image_sha256)
        self.assertEqual(upload["upload_requests"], 1)
        draft = json.loads(
            next((self.fake_blog / "drafts").glob("*.json")).read_text("utf-8")
        )
        self.assertEqual(draft["request"], request)
        raw_response = json.loads(
            (task_directory / "delivery" / "response-raw.json").read_text("utf-8")
        )
        normalized = json.loads(
            (task_directory / "delivery" / "response.json").read_text("utf-8")
        )
        self.assertEqual(raw_response["state"], "draft_accepted")
        self.assertEqual(normalized["draft_id"], raw_response["draft_ref"])
        self.assertEqual(normalized["status"], "accepted")

    def test_unknown_acceptance_retries_with_one_idempotent_draft(self) -> None:
        self.fake_blog.mkdir(parents=True)
        (self.fake_blog / "control.json").write_text(
            json.dumps(
                {
                    "create_draft_failures": [
                        {
                            "effect": "accept_then_timeout",
                            "category": "transient",
                            "code": "response_lost",
                            "message": "Connection closed after acceptance",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.append_submission()

        first = self.run_intake()

        task_id = first["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        first_task = json.loads(
            (task_directory / "task.json").read_text("utf-8")
        )
        request_path = task_directory / "delivery" / "request.json"
        request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
        self.assertEqual(first_task["milestone"], "rewrite_artifact_ready")
        self.assertEqual(first_task["blocker"]["kind"], "retry_pending")
        self.assertFalse((task_directory / "delivery" / "response.json").exists())
        first_attempt = (
            task_directory / "delivery" / "attempts" / first["run_id"]
        )
        attempt_error = json.loads(
            (first_attempt / "error.json").read_text("utf-8")
        )
        self.assertEqual(attempt_error["error_code"], "response_lost")
        self.assertEqual(attempt_error["response_received"], False)
        self.assertEqual(len(list((self.fake_blog / "drafts").glob("*.json"))), 1)
        self.assertEqual(
            len(list((self.fake_blog / "idempotency").glob("*.json"))), 1
        )
        request_path.unlink()

        second = self.run_intake()

        completed_task = json.loads(
            (task_directory / "task.json").read_text("utf-8")
        )
        self.assertIn(task_id, second["attempted_task_ids"])
        self.assertEqual(completed_task["milestone"], "draft_delivery_confirmed")
        self.assertEqual(len(list((self.fake_blog / "drafts").glob("*.json"))), 1)
        self.assertEqual(
            hashlib.sha256(request_path.read_bytes()).hexdigest(), request_hash
        )
        draft = json.loads(
            next((self.fake_blog / "drafts").glob("*.json")).read_text("utf-8")
        )
        self.assertEqual(completed_task["external_draft"]["draft_id"], draft["response"]["draft_ref"])

    def test_malicious_response_is_attempt_evidence_and_does_not_stop_queue(
        self,
    ) -> None:
        self.fake_blog.mkdir(parents=True)
        (self.fake_blog / "control.json").write_text(
            json.dumps(
                {
                    "create_draft_responses": [
                        {
                            "draft_ref": "draft-malicious",
                            "state": "draft_accepted",
                            "preview": "file:///private/secret",
                            "adapter": "fake",
                            "action": "publish",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.append_submission()
        self.append_submission()

        result = self.run_intake()

        task_pairs = [
            (
                self.repository / "tasks" / task_id,
                json.loads(
                    (
                        self.repository / "tasks" / task_id / "task.json"
                    ).read_text("utf-8")
                ),
            )
            for task_id in result["task_ids"]
        ]
        failed = [pair for pair in task_pairs if pair[1]["blocker"] is not None]
        completed = [
            pair
            for pair in task_pairs
            if pair[1]["milestone"] == "draft_delivery_confirmed"
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(len(completed), 1)
        failed_task, failed_record = failed[0]
        completed_task, completed_record = completed[0]
        self.assertEqual(failed_record["milestone"], "rewrite_artifact_ready")
        self.assertEqual(failed_record["blocker"]["kind"], "permanent_failure")
        self.assertEqual(failed_record["blocker"]["error_category"], "invalid_response")
        attempt_raw = json.loads(
            (
                failed_task
                / "delivery"
                / "attempts"
                / result["run_id"]
                / "response-raw.json"
            ).read_text("utf-8")
        )
        self.assertEqual(attempt_raw["action"], "publish")
        self.assertFalse((failed_task / "delivery" / "response.json").exists())
        self.assertEqual(completed_record["milestone"], "draft_delivery_confirmed")
        self.assertEqual(
            {item["status"] for item in result["task_results"]},
            {"permanent_failure", "fake_draft_confirmed"},
        )
        self.assertTrue((completed_task / "delivery" / "response.json").exists())
        self.assertTrue(
            {path.name for path in self.fake_blog.iterdir()}
            <= {"control.json", "drafts", "idempotency", "uploads"}
        )

    def test_hand_edited_generated_request_is_rejected_before_resend(self) -> None:
        self.fake_blog.mkdir(parents=True)
        (self.fake_blog / "control.json").write_text(
            json.dumps(
                {
                    "create_draft_failures": [
                        {
                            "category": "transient",
                            "code": "connect_timeout",
                            "message": "No acceptance response",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.append_submission()
        first = self.run_intake()
        task_id = first["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        request_path = task_directory / "delivery" / "request.json"
        request = json.loads(request_path.read_text("utf-8"))
        request["target"]["external_id"] = "fake-target:attacker"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        second = self.run_intake()

        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(second["task_results"][0]["status"], "permanent_failure")
        self.assertEqual(task["milestone"], "rewrite_artifact_ready")
        self.assertEqual(task["blocker"]["error_category"], "delivery_integrity")
        self.assertEqual(task["blocker"]["error_code"], "delivery_request_invalid")
        self.assertEqual(
            json.loads(request_path.read_text("utf-8"))["target"]["external_id"],
            "fake-target:attacker",
        )
        self.assertFalse((self.fake_blog / "drafts").exists())

    def test_explicit_blog_rejection_is_typed_and_never_completed(self) -> None:
        self.fake_blog.mkdir(parents=True)
        (self.fake_blog / "control.json").write_text(
            json.dumps(
                {
                    "create_draft_responses": [
                        {
                            "draft_ref": "draft-rejected",
                            "state": "rejected",
                            "preview": "https://blog.example.test/rejected",
                            "adapter": "fake",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.append_submission()

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(result["task_results"][0]["status"], "permanent_failure")
        self.assertEqual(task["milestone"], "rewrite_artifact_ready")
        self.assertEqual(task["blocker"]["error_category"], "rejected_response")
        self.assertEqual(task["blocker"]["error_code"], "draft_rejected")
        self.assertFalse((task_directory / "delivery" / "response.json").exists())
        raw = json.loads(
            (
                task_directory
                / "delivery"
                / "attempts"
                / result["run_id"]
                / "response-raw.json"
            ).read_text("utf-8")
        )
        self.assertEqual(raw["state"], "rejected")

    def test_empty_external_draft_identifier_is_not_completion(self) -> None:
        self.fake_blog.mkdir(parents=True)
        (self.fake_blog / "control.json").write_text(
            json.dumps(
                {
                    "create_draft_responses": [
                        {
                            "draft_ref": "",
                            "state": "draft_accepted",
                            "preview": "https://blog.example.test/missing-id",
                            "adapter": "fake",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.append_submission()

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(result["task_results"][0]["status"], "permanent_failure")
        self.assertEqual(task["milestone"], "rewrite_artifact_ready")
        self.assertEqual(task["blocker"]["error_category"], "invalid_response")
        self.assertIsNone(task["external_draft"])
        self.assertFalse((task_directory / "delivery" / "response.json").exists())

    def test_non_object_response_is_preserved_and_does_not_stop_queue(self) -> None:
        self.fake_blog.mkdir(parents=True)
        (self.fake_blog / "control.json").write_text(
            json.dumps(
                {"create_draft_responses": [["publish", "file:///private/secret"]]}
            ),
            encoding="utf-8",
        )
        self.append_submission()
        self.append_submission()

        result = self.run_intake()

        task_pairs = [
            (
                self.repository / "tasks" / task_id,
                json.loads(
                    (
                        self.repository / "tasks" / task_id / "task.json"
                    ).read_text("utf-8")
                ),
            )
            for task_id in result["task_ids"]
        ]
        failed = [pair for pair in task_pairs if pair[1]["blocker"] is not None]
        completed = [
            pair
            for pair in task_pairs
            if pair[1]["milestone"] == "draft_delivery_confirmed"
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(len(completed), 1)
        failed_task, failed_record = failed[0]
        self.assertEqual(failed_record["blocker"]["error_category"], "invalid_response")
        raw = json.loads(
            (
                failed_task
                / "delivery"
                / "attempts"
                / result["run_id"]
                / "response-raw.json"
            ).read_text("utf-8")
        )
        self.assertEqual(raw, ["publish", "file:///private/secret"])
        self.assertEqual(
            {item["status"] for item in result["task_results"]},
            {"permanent_failure", "fake_draft_confirmed"},
        )


if __name__ == "__main__":
    unittest.main()
