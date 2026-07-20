from __future__ import annotations

import base64
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/process-weixin-submissions/scripts/process_weixin_submissions.py"
BASELINE_MARKER = "marker_" + "a" * 32
CURRENT_MARKER = "marker_" + "b" * 32
WRONG_MARKER = "marker_" + "c" * 32
MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *(str(argument) for argument in arguments)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class MacosComputerUseIntakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "task-repository"
        self.window = self.root / "captured-window.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def initialize(self, marker_id: str = BASELINE_MARKER) -> dict[str, Any]:
        result = run_cli(
            "initialize",
            "--repository",
            self.repository,
            "--macos-marker-id",
            marker_id,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return cast(dict[str, Any], json.loads(result.stdout))

    def write_window(
        self,
        previous_marker_id: str = BASELINE_MARKER,
        current_marker_id: str = CURRENT_MARKER,
    ) -> None:
        self.window.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "adapter": "macos_computer_use_v1",
                    "conversation": "file-transfer-assistant",
                    "previous_marker_id": previous_marker_id,
                    "current_marker_id": current_marker_id,
                    "messages": [
                        {
                            "message_id": "header-1",
                            "kind": "text",
                            "text": "#投稿\n目标: writer-one",
                        },
                        {
                            "message_id": "article-1",
                            "kind": "official_account_article",
                            "title": "当前 Mac 采集的文章",
                            "computer_use_capture": {
                                "clipboard_text": "这是通过当前 Mac 微信复制取得的正文。",
                                "source_url": None,
                                "article_end_observed": True,
                                "all_static_images_captured": True,
                                "media": [],
                            },
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_macos_marker_and_captured_window_run_through_public_cli(self) -> None:
        initialized = self.initialize()
        self.write_window()

        completed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
            "--rewrite-generator",
            "scripted",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = cast(dict[str, Any], json.loads(completed.stdout))
        self.assertEqual(initialized["intake_adapter"], "macos_computer_use_v1")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["marker_id"], CURRENT_MARKER)
        self.assertEqual(
            result["task_results"][0]["status"], "rewrite_artifact_ready"
        )
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        source = json.loads(
            (task_directory / "sources" / "article.json").read_text("utf-8")
        )
        capture_manifest = json.loads(
            (task_directory / "raw" / "capture" / "manifest.json").read_text(
                "utf-8"
            )
        )
        self.assertEqual(source["title"], "当前 Mac 采集的文章")
        self.assertEqual(source["body"], "这是通过当前 Mac 微信复制取得的正文。")
        self.assertEqual(capture_manifest["adapter"], "macos_computer_use_v1")
        self.assertEqual(
            capture_manifest["article_end"]["method"],
            "computer_use_visual_confirmation",
        )
        repository = json.loads(
            (self.repository / "repository.json").read_text("utf-8")
        )
        self.assertEqual(repository["intake"]["last_marker_id"], CURRENT_MARKER)

    def test_macos_window_must_continue_from_repository_marker(self) -> None:
        self.initialize()
        self.write_window(previous_marker_id=WRONG_MARKER)

        rejected = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
            "--rewrite-generator",
            "scripted",
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("previous marker", rejected.stderr)
        repository = json.loads(
            (self.repository / "repository.json").read_text("utf-8")
        )
        self.assertEqual(repository["intake"]["last_marker_id"], BASELINE_MARKER)
        self.assertEqual(list((self.repository / "tasks").iterdir()), [])

    def test_macos_marker_ids_must_use_the_strict_wire_format(self) -> None:
        rejected = run_cli(
            "initialize",
            "--repository",
            self.repository,
            "--macos-marker-id",
            "marker_not_hex",
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("marker_<32 lowercase hex>", rejected.stderr)

    def test_macos_window_rejects_marker_shaped_text_inside_messages(self) -> None:
        self.initialize()
        self.write_window()
        window = json.loads(self.window.read_text("utf-8"))
        window["messages"].insert(
            0,
            {
                "message_id": "hidden-marker",
                "kind": "text",
                "text": f"#批次 {WRONG_MARKER}",
            },
        )
        self.window.write_text(
            json.dumps(window, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        rejected = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("exclude marker-shaped text", rejected.stderr)

    def test_macos_window_rejects_scripted_capture_disguised_as_real_ui(self) -> None:
        self.initialize()
        self.write_window()
        window = json.loads(self.window.read_text("utf-8"))
        article = window["messages"][1]
        article["scripted_capture"] = article.pop("computer_use_capture")
        self.window.write_text(
            json.dumps(window, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        rejected = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("computer_use_capture", rejected.stderr)
        self.assertEqual(list((self.repository / "tasks").iterdir()), [])

    def test_macos_capture_can_import_wechat_saved_image_from_repository_tmp(
        self,
    ) -> None:
        self.initialize()
        self.write_window()
        staged_image = self.repository / "tmp" / "macos-run" / "001.png"
        staged_image.parent.mkdir(parents=True)
        image_bytes = MINIMAL_PNG
        staged_image.write_bytes(image_bytes)
        window = json.loads(self.window.read_text("utf-8"))
        capture = window["messages"][1]["computer_use_capture"]
        capture["media"] = [
            {
                "kind": "image",
                "mime_type": "image/png",
                "capture_method": "original_bytes",
                "staged_path": str(staged_image),
            }
        ]
        self.window.write_text(
            json.dumps(window, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        completed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
            "--rewrite-generator",
            "scripted",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = cast(dict[str, Any], json.loads(completed.stdout))
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        digest = hashlib.sha256(image_bytes).hexdigest()
        self.assertEqual(
            (task_directory / "raw" / "capture" / "assets" / digest).read_bytes(),
            image_bytes,
        )

    def test_macos_capture_rejects_staged_image_outside_repository_tmp(self) -> None:
        self.initialize()
        self.write_window()
        outside_image = self.root / "outside.png"
        outside_image.write_bytes(b"\x89PNG\r\n\x1a\noutside")
        window = json.loads(self.window.read_text("utf-8"))
        capture = window["messages"][1]["computer_use_capture"]
        capture["media"] = [
            {
                "kind": "image",
                "mime_type": "image/png",
                "capture_method": "original_bytes",
                "staged_path": str(outside_image),
            }
        ]
        self.window.write_text(
            json.dumps(window, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        rejected = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
            "--rewrite-generator",
            "scripted",
        )

        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        result = cast(dict[str, Any], json.loads(rejected.stdout))
        self.assertEqual(
            result["task_results"][0]["status"], "permanent_failure"
        )
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(task["blocker"]["error_code"], "invalid_capture_evidence")
        self.assertIn("repository tmp", task["blocker"]["message"])

    def test_macos_capture_rejects_staged_bytes_that_do_not_match_mime(self) -> None:
        self.initialize()
        self.write_window()
        staged_image = self.repository / "tmp" / "macos-run" / "001.png"
        staged_image.parent.mkdir(parents=True)
        staged_image.write_bytes(b"\xff\xd8jpeg-bytes\xff\xd9")
        window = json.loads(self.window.read_text("utf-8"))
        window["messages"][1]["computer_use_capture"]["media"] = [
            {
                "kind": "image",
                "mime_type": "image/png",
                "capture_method": "original_bytes",
                "staged_path": str(staged_image),
            }
        ]
        self.window.write_text(
            json.dumps(window, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        completed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
            "--rewrite-generator",
            "scripted",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = cast(dict[str, Any], json.loads(completed.stdout))
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(task["blocker"]["error_code"], "invalid_capture_evidence")
        self.assertIn("does not match", task["blocker"]["message"])

    def test_macos_scripted_generator_cannot_be_auto_published(self) -> None:
        self.initialize()
        self.write_window()

        rejected = run_cli(
            "run",
            "--repository",
            self.repository,
            "--macos-window",
            self.window,
            "--rewrite-generator",
            "scripted",
            "--publication",
            "auto",
            "--fake-blog-directory",
            self.root / "fake-blog",
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("cannot be automatically published", rejected.stderr)

    def test_macos_run_uses_default_prompt_with_running_codex_generator(self) -> None:
        self.initialize()
        self.write_window()
        prompt_log = self.root / "prompt.txt"
        fake_codex = self.root / "fake-codex"
        fake_codex.write_text(
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

prompt = sys.stdin.read()
pathlib.Path(os.environ["FAKE_CODEX_PROMPT_LOG"]).write_text(prompt, encoding="utf-8")
output_path = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
output_path.write_text(
    json.dumps(
        {
            "title": "在当前 Mac 上跑通内容自动化",
            "markdown": "# 在当前 Mac 上跑通内容自动化\\n\\n这是一篇由运行 Agent 生成并通过确定性校验的文章。\\n",
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
""",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        old_prompt_log = os.environ.get("FAKE_CODEX_PROMPT_LOG")
        os.environ["FAKE_CODEX_PROMPT_LOG"] = str(prompt_log)
        try:
            completed = run_cli(
                "run",
                "--repository",
                self.repository,
                "--macos-window",
                self.window,
                "--codex-command",
                fake_codex,
            )
        finally:
            if old_prompt_log is None:
                os.environ.pop("FAKE_CODEX_PROMPT_LOG", None)
            else:
                os.environ["FAKE_CODEX_PROMPT_LOG"] = old_prompt_log

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = cast(dict[str, Any], json.loads(completed.stdout))
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        content = (task_directory / "rewrite" / "content.md").read_text("utf-8")
        manifest = json.loads(
            (task_directory / "rewrite" / "manifest.json").read_text("utf-8")
        )
        prompt = prompt_log.read_text("utf-8")
        self.assertIn("# 在当前 Mac 上跑通内容自动化", content)
        self.assertEqual(manifest["generator"], "running_agent_v1")
        self.assertIn("## 事实与归因", prompt)
        self.assertIn("这是通过当前 Mac 微信复制取得的正文。", prompt)
        self.assertNotIn("real Agent rewrite generation", result["missing_capabilities"])
