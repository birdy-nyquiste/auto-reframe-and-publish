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
sys.path.insert(0, str(CLI.parent))

from weixin_submission.blob_upload import (  # noqa: E402
    FakePublicBlobUploader,
    UploadedImage,
)
from weixin_submission.publication import (  # noqa: E402
    FakePublicationAdapter,
    _build_image_plan,
    _publication_body,
    _validate_uploaded_image_record,
    publish_rewrite,
    resume_planned_image_publication,
)
from weixin_submission.rewrite import RewriteArtifact  # noqa: E402
from weixin_submission.storage import WorkflowError  # noqa: E402


class InterruptAfterOneUpload:
    def __init__(self, inner: FakePublicBlobUploader) -> None:
        self.inner = inner
        self.calls = 0

    @property
    def destination_id(self) -> str:
        return self.inner.destination_id

    def upload(
        self, source: Path, *, pathname: str, content_type: str
    ) -> UploadedImage:
        self.calls += 1
        if self.calls == 2:
            raise KeyboardInterrupt("simulated image upload interruption")
        return self.inner.upload(
            source, pathname=pathname, content_type=content_type
        )

    def accepts_public_url(self, url: str) -> bool:
        return self.inner.accepts_public_url(url)


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
                    "text": f"#投稿\nauthor.name: author-{suffix}",
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

    def test_explicit_publish_can_create_audited_text_only_version(self) -> None:
        self.append_submission("text-only")
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        article = chat["messages"][-1]
        article.pop("body")
        article.pop("source_url")
        article.pop("images")
        article["scripted_capture"] = {
            "clipboard_text": "Body with one captured image.",
            "source_url": "https://example.com/text-only",
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
        content_result = self.run_without_publication()
        task_id = content_result["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        rewrite_commit_before = (task_directory / "rewrite" / "commit.json").read_bytes()
        fake_blog = self.root / "fake-public-blog"

        preserved = run_cli(
            "publish",
            "--repository",
            self.repository,
            "--task-id",
            task_id,
            "--fake-blog-directory",
            fake_blog,
        )
        self.assertEqual(preserved.returncode, 0, preserved.stderr)
        preserved_result = cast(dict[str, Any], json.loads(preserved.stdout))
        self.assertEqual(
            preserved_result["publication_result"]["blocker_reason"],
            "public_image_urls_missing",
        )

        published = run_cli(
            "publish",
            "--repository",
            self.repository,
            "--task-id",
            task_id,
            "--image-policy",
            "omit",
            "--fake-blog-directory",
            fake_blog,
        )
        self.assertEqual(published.returncode, 0, published.stderr)
        result = cast(dict[str, Any], json.loads(published.stdout))
        publication_result = result["publication_result"]
        self.assertEqual(publication_result["status"], "publication_confirmed")
        publication_directory = (
            self.repository
            / "publications"
            / publication_result["publication_id"]
        )
        publication = cast(
            dict[str, Any],
            json.loads((publication_directory / "publication.json").read_text("utf-8")),
        )
        request = cast(
            dict[str, Any],
            json.loads((publication_directory / "request.json").read_text("utf-8")),
        )
        self.assertEqual(publication["presentation"]["image_policy"], "omit")
        self.assertEqual(request["images"], [])
        self.assertTrue(Path(result["report_path"]).exists())
        self.assertEqual(
            (task_directory / "rewrite" / "commit.json").read_bytes(),
            rewrite_commit_before,
        )
        self.assertEqual(len(list((fake_blog / "posts").glob("*.json"))), 1)

    def test_explicit_publish_uploads_referenced_images_and_records_cover(self) -> None:
        self.append_submission("with-images")
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        article = chat["messages"][-1]
        article.pop("body")
        article.pop("source_url")
        article.pop("images")
        article["scripted_capture"] = {
            "clipboard_text": "Body with one captured image.",
            "source_url": "https://example.com/with-images",
            "article_end_observed": True,
            "all_static_images_captured": True,
            "media": [
                {
                    "kind": "image",
                    "mime_type": "image/png",
                    "capture_method": "original_bytes",
                    "bytes_base64": base64.b64encode(
                        b"\x89PNG\r\n\x1a\nfixture-image"
                    ).decode("ascii"),
                }
            ],
        }
        self.chat.write_text(json.dumps(chat), encoding="utf-8")
        fake_codex = self.root / "fake-codex-with-image"
        fake_codex.write_text(
            """#!/usr/bin/env python3
import json
import pathlib
import sys

output_path = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
output_path.write_text(
    json.dumps(
        {
            "title": "Article with-images",
            "markdown": "# Article with-images\\n\\nBody.\\n\\n![Image 1](source-image-001.png)\\n",
        }
    ),
    encoding="utf-8",
)
""",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        generated = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--rewrite-generator",
            "codex",
            "--codex-command",
            fake_codex,
        )
        self.assertEqual(generated.returncode, 0, generated.stderr)
        content_result = cast(dict[str, Any], json.loads(generated.stdout))
        task_id = content_result["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        rewrite_commit_before = (task_directory / "rewrite" / "commit.json").read_bytes()
        fake_blog = self.root / "fake-public-blog"
        fake_blob = self.root / "fake-public-blob"

        published = run_cli(
            "publish",
            "--repository",
            self.repository,
            "--task-id",
            task_id,
            "--image-policy",
            "upload",
            "--cover-image",
            "source-image-001.png",
            "--fake-blob-directory",
            fake_blob,
            "--fake-blog-directory",
            fake_blog,
        )

        self.assertEqual(published.returncode, 0, published.stderr)
        result = cast(dict[str, Any], json.loads(published.stdout))
        publication_result = result["publication_result"]
        self.assertEqual(publication_result["status"], "publication_confirmed")
        publication_directory = (
            self.repository / "publications" / publication_result["publication_id"]
        )
        publication = cast(
            dict[str, Any],
            json.loads((publication_directory / "publication.json").read_text("utf-8")),
        )
        request = cast(
            dict[str, Any],
            json.loads((publication_directory / "request.json").read_text("utf-8")),
        )
        self.assertEqual(publication["presentation"]["image_policy"], "upload")
        self.assertEqual(len(request["images"]), 1)
        image_url = request["images"][0]
        self.assertTrue(image_url.startswith("https://fake-public-blob.example/"))
        self.assertEqual(request["cover_image"], image_url)
        self.assertIn(f"![Image 1]({image_url})", request["body_markdown"])
        self.assertEqual(
            publication["presentation"]["cover_image_source"],
            "source-image-001.png",
        )
        self.assertEqual(publication["presentation"]["cover_image_url"], image_url)
        self.assertEqual(len(publication["presentation"]["resolved_images"]), 1)
        self.assertEqual(len(list((fake_blob / "objects").glob("*"))), 1)
        self.assertEqual(
            (task_directory / "rewrite" / "commit.json").read_bytes(),
            rewrite_commit_before,
        )

    def test_text_only_body_removes_markdown_images_deterministically(self) -> None:
        artifact = RewriteArtifact(
            title="Title",
            content=(
                "# Title\n\nBefore.\n\n"
                "![First](source-image-001.jpg)\n\n"
                "Between ![Second](source-image-002.jpg) text.\n"
            ),
            target_id="author",
            images=("one", "two"),
        )

        body, presentation = _publication_body(artifact, "omit")

        self.assertEqual(body, "# Title\n\nBefore.\n\nBetween  text.\n")
        self.assertEqual(presentation["omitted_markdown_image_count"], 2)
        self.assertNotEqual(
            presentation["source_body_sha256"],
            presentation["published_body_sha256"],
        )

    def test_image_plan_excludes_captured_images_not_used_by_the_rewrite(self) -> None:
        task_directory = self.root / "planned-task"
        asset_directory = task_directory / "raw" / "capture" / "assets"
        asset_directory.mkdir(parents=True)
        image_paths: list[str] = []
        for position in range(1, 4):
            relative = f"raw/capture/assets/image-{position}"
            (task_directory / relative).write_bytes(
                b"\xff\xd8\xff" + bytes([position])
            )
            image_paths.append(relative)
        artifact = RewriteArtifact(
            title="Title",
            content=(
                "# Title\n\n"
                "![First](source-image-001.jpg)\n\n"
                "![Second](source-image-002.jpg)\n"
            ),
            target_id="author",
            images=tuple(image_paths),
        )

        plan = _build_image_plan(
            task_directory,
            artifact,
            cover_image="source-image-001.jpg",
            destination="fake://blob",
        )

        self.assertEqual(
            [item["source_name"] for item in plan["images"]],
            ["source-image-001.jpg", "source-image-002.jpg"],
        )
        self.assertNotIn("image-3", json.dumps(plan))

    def test_interrupted_image_upload_resumes_the_same_publication(self) -> None:
        self.append_submission("resume-images")
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        article = chat["messages"][-1]
        article.pop("body")
        article.pop("source_url")
        article.pop("images")
        article["scripted_capture"] = {
            "clipboard_text": "Body with two captured images.",
            "source_url": "https://example.com/resume-images",
            "article_end_observed": True,
            "all_static_images_captured": True,
            "media": [
                {
                    "kind": "image",
                    "mime_type": "image/png",
                    "capture_method": "original_bytes",
                    "bytes_base64": base64.b64encode(
                        b"\x89PNG\r\n\x1a\nfirst"
                    ).decode("ascii"),
                },
                {
                    "kind": "image",
                    "mime_type": "image/png",
                    "capture_method": "original_bytes",
                    "bytes_base64": base64.b64encode(
                        b"\x89PNG\r\n\x1a\nsecond"
                    ).decode("ascii"),
                },
            ],
        }
        self.chat.write_text(json.dumps(chat), encoding="utf-8")
        fake_codex = self.root / "fake-codex-two-images"
        fake_codex.write_text(
            """#!/usr/bin/env python3
import json
import pathlib
import sys

output_path = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
output_path.write_text(
    json.dumps(
        {
            "title": "Article resume-images",
            "markdown": "# Article resume-images\\n\\n![One](source-image-001.png)\\n\\n![Two](source-image-002.png)\\n",
        }
    ),
    encoding="utf-8",
)
""",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        generated = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--rewrite-generator",
            "codex",
            "--codex-command",
            fake_codex,
        )
        self.assertEqual(generated.returncode, 0, generated.stderr)
        task_id = cast(dict[str, Any], json.loads(generated.stdout))["task_ids"][0]
        fake_blog = FakePublicationAdapter(self.root / "fake-resume-blog")
        blob = FakePublicBlobUploader(self.root / "fake-resume-blob")
        interrupted_blob = InterruptAfterOneUpload(blob)

        with self.assertRaises(KeyboardInterrupt):
            publish_rewrite(
                self.repository,
                task_id,
                "run_interrupted_images",
                fake_blog,
                image_policy="upload",
                image_uploader=interrupted_blob,
                cover_image="source-image-001.png",
            )

        publication_directories = list((self.repository / "publications").iterdir())
        self.assertEqual(len(publication_directories), 1)
        publication_id = publication_directories[0].name
        self.assertEqual(
            len(list((publication_directories[0] / "image-assets").glob("*.json"))),
            1,
        )
        image_events = [
            json.loads(path.read_text("utf-8"))
            for path in (publication_directories[0] / "events").glob("*.json")
        ]
        self.assertEqual(
            [event["type"] for event in image_events].count("image_uploaded"), 1
        )
        with self.assertRaises(WorkflowError):
            resume_planned_image_publication(
                self.repository,
                task_id,
                "run_wrong_blog_destination",
                FakePublicationAdapter(self.root / "another-blog"),
                interrupted_blob,
            )

        resumed = resume_planned_image_publication(
            self.repository,
            task_id,
            "run_resumed_images",
            fake_blog,
            interrupted_blob,
        )

        self.assertIsNotNone(resumed)
        assert resumed is not None
        self.assertEqual(resumed[0], publication_id)
        self.assertEqual(resumed[1]["status"], "publication_confirmed")
        self.assertEqual(interrupted_blob.calls, 3)
        self.assertEqual(
            len(list((publication_directories[0] / "image-assets").glob("*.json"))),
            2,
        )
        self.assertEqual(
            len(list((self.root / "fake-resume-blob" / "objects").glob("*"))),
            2,
        )

    def test_durable_image_record_requires_exact_type_and_blob_destination(self) -> None:
        planned = {
            "source_name": "source-image-001.jpg",
            "asset_sha256": "abc",
            "pathname": "weixin-blog-publish/assets/abc.jpg",
            "content_type": "image/jpeg",
            "is_cover": True,
        }
        record = {
            **planned,
            "content_type": "image/png",
            "url": "https://attacker.example/image.jpg",
        }

        with self.assertRaises(WorkflowError):
            _validate_uploaded_image_record(
                planned,
                record,
                FakePublicBlobUploader(self.root / "fake-validation-blob"),
            )

    def test_missing_api_key_blocks_before_http_without_target_mapping(self) -> None:
        self.append_submission("unmapped")
        config = self.root / "blog-config.json"
        config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.invalid/api/v1",
                    "api_key_env": "UNSET_TEST_KEY",
                }
            ),
            encoding="utf-8",
        )

        result = self.run_without_publication(
            "--publication", "auto", "--blog-config", config
        )

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "needs_configuration")
        self.assertEqual(publication["blocker_reason"], "api_key_missing")


if __name__ == "__main__":
    unittest.main()
