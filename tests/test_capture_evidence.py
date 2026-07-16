from __future__ import annotations

import base64
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


class CaptureEvidenceTest(unittest.TestCase):
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

    def append_captured_article(self, capture: dict[str, Any]) -> None:
        chat = json.loads(self.chat.read_text("utf-8"))
        chat["messages"].extend(
            [
                {
                    "message_id": "capture-header",
                    "kind": "text",
                    "text": "#投稿\n目标: author-capture",
                },
                {
                    "message_id": "capture-article",
                    "kind": "official_account_article",
                    "title": "复制正文采集",
                    "scripted_capture": capture,
                },
            ]
        )
        self.chat.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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

    def test_copied_body_without_source_url_is_complete_when_article_end_is_observed(
        self,
    ) -> None:
        body = "这是通过文章界面复制粘贴取得的权威正文。\n第二段保持原样。"
        self.append_captured_article(
            {
                "clipboard_text": body,
                "source_url": None,
                "article_end_observed": True,
                "media": [],
            }
        )

        result = self.run_intake()

        task_id = result["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        source = json.loads(
            (task_directory / "sources" / "article.json").read_text("utf-8")
        )
        self.assertEqual(result["task_results"][0]["status"], "fake_draft_confirmed")
        self.assertEqual(
            (task_directory / "raw" / "capture" / "clipboard.txt").read_text(
                "utf-8"
            ),
            body,
        )
        self.assertEqual(manifest["body"]["method"], "copy_paste")
        self.assertIsNone(manifest["source_url"])
        self.assertTrue(manifest["article_end"]["observed"])
        self.assertTrue(manifest["completeness"]["complete"])
        self.assertEqual(source["body"], body)
        self.assertIsNone(source["source_url"])

    def test_duplicate_image_bytes_are_stored_once_without_losing_occurrences(
        self,
    ) -> None:
        first_image = base64.b64encode(b"first-static-image").decode("ascii")
        second_image = base64.b64encode(b"second-static-image").decode("ascii")
        self.append_captured_article(
            {
                "clipboard_text": "正文足够完整，并包含三次图片出现。",
                "source_url": "https://example.com/images",
                "article_end_observed": True,
                "media": [
                    {
                        "kind": "image",
                        "mime_type": "image/jpeg",
                        "capture_method": "original_bytes",
                        "bytes_base64": first_image,
                    },
                    {
                        "kind": "image",
                        "mime_type": "image/png",
                        "capture_method": "original_bytes",
                        "bytes_base64": first_image,
                    },
                    {
                        "kind": "image",
                        "mime_type": "image/jpeg",
                        "capture_method": "original_bytes",
                        "bytes_base64": second_image,
                    },
                ],
            }
        )

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        source = json.loads(
            (task_directory / "sources" / "article.json").read_text("utf-8")
        )
        occurrences = manifest["image_occurrences"]
        assets = list((task_directory / "raw" / "capture" / "assets").iterdir())
        self.assertEqual([item["position"] for item in occurrences], [1, 2, 3])
        self.assertEqual(
            occurrences[0]["asset_sha256"], occurrences[1]["asset_sha256"]
        )
        self.assertNotEqual(
            occurrences[1]["asset_sha256"], occurrences[2]["asset_sha256"]
        )
        self.assertEqual(len(assets), 2)
        self.assertEqual(
            [image["asset_path"] for image in source["images"]],
            [item["asset_path"] for item in occurrences],
        )

    def test_viewport_crop_preserves_unmodified_screenshot_evidence(self) -> None:
        crop_bytes = b"cropped-static-image"
        viewport_bytes = b"unmodified-article-viewport"
        self.append_captured_article(
            {
                "clipboard_text": "正文完整，但这张图片只能通过视口截图降级取得。",
                "source_url": None,
                "article_end_observed": True,
                "media": [
                    {
                        "kind": "image",
                        "mime_type": "image/png",
                        "capture_method": "viewport_crop",
                        "bytes_base64": base64.b64encode(crop_bytes).decode("ascii"),
                        "viewport_mime_type": "image/png",
                        "viewport_bytes_base64": base64.b64encode(
                            viewport_bytes
                        ).decode("ascii"),
                        "crop": {"x": 10, "y": 20, "width": 300, "height": 180},
                    }
                ],
            }
        )

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        occurrence = manifest["image_occurrences"][0]
        viewport = occurrence["viewport_evidence"]
        self.assertEqual(occurrence["capture_method"], "viewport_crop")
        self.assertEqual(occurrence["degradation"], "screenshot_crop")
        self.assertEqual(viewport["crop"], {"x": 10, "y": 20, "width": 300, "height": 180})
        self.assertEqual((task_directory / occurrence["asset_path"]).read_bytes(), crop_bytes)
        self.assertEqual((task_directory / viewport["path"]).read_bytes(), viewport_bytes)

    def test_gif_is_reduced_to_a_static_frame_and_embedded_media_is_not_inferred(
        self,
    ) -> None:
        frame_bytes = b"gif-static-frame"
        self.append_captured_article(
            {
                "clipboard_text": "这篇文章有充分的复制正文，因此未采集的音视频不会阻止处理继续。",
                "source_url": "https://example.com/mixed-media",
                "article_end_observed": True,
                "media": [
                    {
                        "kind": "gif",
                        "static_frame_mime_type": "image/png",
                        "static_frame_bytes_base64": base64.b64encode(
                            frame_bytes
                        ).decode("ascii"),
                    },
                    {"kind": "video"},
                    {"kind": "audio"},
                ],
            }
        )

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        source = json.loads(
            (task_directory / "sources" / "article.json").read_text("utf-8")
        )
        gif = manifest["image_occurrences"][0]
        self.assertEqual(result["task_results"][0]["status"], "fake_draft_confirmed")
        self.assertEqual(gif["source_kind"], "gif")
        self.assertEqual(gif["capture_method"], "static_frame")
        self.assertEqual(gif["degradation"], "animation_removed")
        self.assertEqual((task_directory / gif["asset_path"]).read_bytes(), frame_bytes)
        self.assertEqual(
            [item["kind"] for item in manifest["embedded_media"]],
            ["video", "audio"],
        )
        self.assertTrue(
            all(not item["downloaded"] for item in manifest["embedded_media"])
        )
        self.assertTrue(
            all(not item["transcribed"] for item in manifest["embedded_media"])
        )
        self.assertEqual(source["images"][0]["source_kind"], "gif")
        self.assertEqual(source["images"][0]["article_position"], 1)
        self.assertEqual(len(source["media_limitations"]), 2)

    def test_media_primary_article_with_insufficient_text_fails_permanently(
        self,
    ) -> None:
        self.append_captured_article(
            {
                "clipboard_text": "仅视频",
                "source_url": "https://example.com/media-only",
                "article_end_observed": True,
                "media": [{"kind": "video"}],
            }
        )

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(result["task_results"][0]["status"], "permanent_failure")
        self.assertEqual(task["milestone"], "task_created")
        self.assertEqual(task["blocker"]["operation"], "capture_raw_evidence")
        self.assertEqual(task["blocker"]["error_code"], "media_only_source")
        self.assertTrue(
            (task_directory / "raw" / "capture" / "manifest.json").exists()
        )

    def test_capture_does_not_commit_when_article_end_was_not_observed(self) -> None:
        self.append_captured_article(
            {
                "clipboard_text": "虽然复制到了正文片段，但没有观察到文章结束位置。",
                "source_url": None,
                "article_end_observed": False,
                "media": [],
            }
        )

        result = self.run_intake()

        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        self.assertEqual(task["milestone"], "task_created")
        self.assertEqual(task["blocker"]["kind"], "retry_pending")
        self.assertEqual(task["blocker"]["error_code"], "article_end_not_observed")
        self.assertFalse(manifest["completeness"]["complete"])

    def test_structured_source_rebuild_rejects_corrupted_image_evidence(self) -> None:
        self.append_captured_article(
            {
                "clipboard_text": "正文完整，并且图片证据应当通过哈希完整性检查。",
                "source_url": "https://example.com/integrity",
                "article_end_observed": True,
                "media": [
                    {
                        "kind": "image",
                        "mime_type": "image/png",
                        "capture_method": "original_bytes",
                        "bytes_base64": base64.b64encode(b"trusted-image").decode(
                            "ascii"
                        ),
                    }
                ],
            }
        )
        interrupted = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
            "--simulate-interruption-after",
            "raw_evidence_ready",
        )
        self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
        task_directory = next((self.repository / "tasks").iterdir())
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        asset_path = task_directory / manifest["image_occurrences"][0]["asset_path"]
        asset_path.write_bytes(b"corrupted-image")

        resumed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
        )

        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(resumed.returncode, 2)
        self.assertIn("Capture evidence hash mismatch", resumed.stderr)
        self.assertEqual(task["milestone"], "raw_evidence_ready")

    def test_structured_source_rebuild_rejects_corrupted_viewport_evidence(
        self,
    ) -> None:
        self.append_captured_article(
            {
                "clipboard_text": "正文完整，截图裁剪也必须保留并验证原始视口证据。",
                "source_url": None,
                "article_end_observed": True,
                "media": [
                    {
                        "kind": "image",
                        "mime_type": "image/png",
                        "capture_method": "viewport_crop",
                        "bytes_base64": base64.b64encode(b"crop").decode("ascii"),
                        "viewport_mime_type": "image/png",
                        "viewport_bytes_base64": base64.b64encode(
                            b"whole-viewport"
                        ).decode("ascii"),
                        "crop": {"x": 0, "y": 1, "width": 20, "height": 30},
                    }
                ],
            }
        )
        interrupted = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
            "--simulate-interruption-after",
            "raw_evidence_ready",
        )
        self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
        task_directory = next((self.repository / "tasks").iterdir())
        manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        viewport = manifest["image_occurrences"][0]["viewport_evidence"]
        (task_directory / viewport["path"]).write_bytes(b"corrupted-viewport")

        resumed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
        )

        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(resumed.returncode, 2)
        self.assertIn("Capture evidence hash mismatch", resumed.stderr)
        self.assertEqual(task["milestone"], "raw_evidence_ready")


if __name__ == "__main__":
    unittest.main()
