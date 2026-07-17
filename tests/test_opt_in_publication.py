from __future__ import annotations

import json
import base64
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


class OptInPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "task-repository"
        self.chat = self.root / "scripted-chat.json"
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

    def append_submission(self, suffix: str) -> None:
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        chat["messages"].extend(
            [
                {
                    "message_id": f"header-{suffix}",
                    "kind": "text",
                    "text": f"#投稿\n目标: author-{suffix}",
                },
                {
                    "message_id": f"article-{suffix}",
                    "kind": "official_account_article",
                    "title": f"Article {suffix}",
                    "body": f"Copied body {suffix}.",
                    "source_url": f"https://example.com/{suffix}",
                    "images": [],
                },
            ]
        )
        self.chat.write_text(json.dumps(chat), encoding="utf-8")

    def run_without_publication(self, *extra: object) -> dict[str, Any]:
        result = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            *extra,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return cast(dict[str, Any], json.loads(result.stdout))

    def assert_content_only(self, result: dict[str, Any]) -> None:
        task_id = result["task_ids"][0]
        task = cast(
            dict[str, Any],
            json.loads(
                (self.repository / "tasks" / task_id / "task.json").read_text("utf-8")
            ),
        )
        run = cast(
            dict[str, Any],
            json.loads(
                (self.repository / "runs" / result["run_id"] / "run.json").read_text(
                    "utf-8"
                )
            ),
        )

        self.assertEqual(task["milestone"], "rewrite_artifact_ready")
        self.assertNotIn("delivery_mode", task)
        self.assertNotIn("external_draft", task)
        self.assertEqual(result["task_results"][0]["status"], "rewrite_artifact_ready")
        self.assertEqual(run["publication_selection"], "none")
        self.assertEqual(result["publication_selection"], "none")
        self.assertEqual(run["created_publication_ids"], [])
        self.assertEqual(run["attempted_publication_ids"], [])
        self.assertEqual(list((self.repository / "publications").iterdir()), [])

    def test_omitted_publication_selection_does_not_publish(self) -> None:
        self.append_submission("default")
        self.assert_content_only(self.run_without_publication())

    def test_explicit_none_does_not_publish(self) -> None:
        self.append_submission("none")
        self.assert_content_only(self.run_without_publication("--publication", "none"))

    def test_explicit_auto_creates_and_executes_an_independent_publication(
        self,
    ) -> None:
        self.append_submission("auto")
        fake_blog = self.root / "fake-public-blog"
        result = self.run_without_publication(
            "--publication",
            "auto",
            "--fake-blog-directory",
            fake_blog,
        )

        self.assertEqual(result["task_results"][0]["status"], "rewrite_artifact_ready")
        self.assertEqual(len(result["publication_results"]), 1)
        publication_result = result["publication_results"][0]
        self.assertEqual(publication_result["status"], "publication_confirmed")
        self.assertTrue(publication_result["public_url"].startswith("https://"))

        publication_id = publication_result["publication_id"]
        publication_directory = self.repository / "publications" / publication_id
        publication = cast(
            dict[str, Any],
            json.loads((publication_directory / "publication.json").read_text("utf-8")),
        )
        run = cast(
            dict[str, Any],
            json.loads(
                (self.repository / "runs" / result["run_id"] / "run.json").read_text(
                    "utf-8"
                )
            ),
        )

        self.assertEqual(publication["task_id"], result["task_ids"][0])
        self.assertEqual(publication["milestone"], "publication_confirmed")
        self.assertEqual(
            publication["external_result"]["public_url"],
            publication_result["public_url"],
        )
        self.assertEqual(run["publication_selection"], "auto")
        self.assertEqual(run["created_publication_ids"], [publication_id])
        self.assertEqual(run["attempted_publication_ids"], [publication_id])
        self.assertEqual(
            len(list((publication_directory / "events").glob("*.json"))),
            3,
        )
        self.assertEqual(len(list((fake_blog / "posts").glob("*.json"))), 1)
        status = run_cli("status", "--repository", self.repository)
        self.assertEqual(status.returncode, 0, status.stderr)
        status_result = cast(dict[str, Any], json.loads(status.stdout))
        self.assertEqual(status_result["publication_count"], 1)
        self.assertEqual(
            status_result["publication_milestones"],
            {"publication_confirmed": 1},
        )

    def test_one_publication_failure_does_not_stop_another(self) -> None:
        self.append_submission("first")
        self.append_submission("second")
        fake_blog = self.root / "fake-public-blog"
        fake_blog.mkdir()
        (fake_blog / "control.json").write_text(
            json.dumps(
                {
                    "publish_failures": [
                        {
                            "kind": "permanent_failure",
                            "code": "scripted_rejection",
                            "message": "First publication was rejected",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = self.run_without_publication(
            "--publication", "auto", "--fake-blog-directory", fake_blog
        )

        self.assertEqual(
            [item["status"] for item in result["publication_results"]],
            ["permanent_failure", "publication_confirmed"],
        )
        self.assertEqual(len(list((fake_blog / "posts").glob("*.json"))), 1)

    def test_interruption_after_rewrite_does_not_strand_authorized_publication(
        self,
    ) -> None:
        self.append_submission("interrupted-auto")
        fake_blog = self.root / "fake-public-blog"
        interrupted = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--publication",
            "auto",
            "--fake-blog-directory",
            fake_blog,
            "--simulate-interruption-after",
            "rewrite_artifact_ready",
        )
        self.assertEqual(interrupted.returncode, 2, interrupted.stderr)

        publications = list((self.repository / "publications").iterdir())
        self.assertEqual(len(publications), 1)
        publication = cast(
            dict[str, Any],
            json.loads((publications[0] / "publication.json").read_text("utf-8")),
        )
        self.assertEqual(publication["milestone"], "publication_confirmed")
        self.assertEqual(len(list((fake_blog / "posts").glob("*.json"))), 1)

        resumed = self.run_without_publication()
        self.assertEqual(resumed["publication_results"], [])
        self.assertEqual(len(list((fake_blog / "posts").glob("*.json"))), 1)

    def test_local_images_block_publication_instead_of_being_dropped(self) -> None:
        self.append_submission("image")
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        article = chat["messages"][-1]
        article.pop("body")
        article.pop("source_url")
        article.pop("images")
        article["scripted_capture"] = {
            "clipboard_text": "Body with one required image.",
            "source_url": "https://example.com/image",
            "article_end_observed": True,
            "all_static_images_captured": True,
            "media": [
                {
                    "kind": "image",
                    "mime_type": "image/png",
                    "capture_method": "original_bytes",
                    "bytes_base64": base64.b64encode(b"image-bytes").decode("ascii"),
                }
            ],
        }
        self.chat.write_text(json.dumps(chat), encoding="utf-8")
        fake_blog = self.root / "fake-public-blog"

        result = self.run_without_publication(
            "--publication", "auto", "--fake-blog-directory", fake_blog
        )

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "needs_configuration")
        self.assertEqual(publication["blocker_reason"], "public_image_urls_missing")
        publication_directory = (
            self.repository / "publications" / publication["publication_id"]
        )
        self.assertFalse((publication_directory / "request.json").exists())
        self.assertFalse((fake_blog / "posts").exists())

    def test_missing_target_mapping_blocks_before_http(self) -> None:
        self.append_submission("unmapped")
        config = self.root / "blog-config.json"
        config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.invalid/api/v1",
                    "api_key_env": "UNSET_TEST_KEY",
                    "targets": {},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_without_publication(
            "--publication", "auto", "--blog-config", config
        )

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "needs_configuration")
        self.assertEqual(publication["blocker_reason"], "target_mapping_missing")


if __name__ == "__main__":
    unittest.main()
