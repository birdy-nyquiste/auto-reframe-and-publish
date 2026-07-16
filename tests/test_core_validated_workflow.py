from __future__ import annotations

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


def submission(prefix: str, target: str) -> list[dict[str, object]]:
    return [
        {
            "message_id": f"{prefix}-header",
            "kind": "text",
            "text": f"#投稿\n目标: {target}",
        },
        {
            "message_id": f"{prefix}-article",
            "kind": "official_account_article",
            "title": f"Article {prefix}",
            "body": f"Copied body {prefix}.",
            "source_url": f"https://example.com/{prefix}",
            "images": [],
        },
    ]


class CoreValidatedWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "task-repository"
        self.chat = self.root / "scripted-chat.json"
        self.clipboard = self.root / "scripted-clipboard.json"
        self.fake_blog = self.root / "fake-blog"
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
        self.write_clipboard("sensitive value that must not be preserved")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_clipboard(self, text: str, owner_id: str | None = None) -> None:
        self.clipboard.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "owner_id": owner_id,
                    "text": text,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def clipboard_record(self) -> dict[str, object]:
        return cast(
            dict[str, object], json.loads(self.clipboard.read_text(encoding="utf-8"))
        )

    def initialize(self) -> dict[str, Any]:
        result = run_cli(
            "initialize",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--scripted-clipboard",
            self.clipboard,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return cast(dict[str, Any], json.loads(result.stdout))

    def append_messages(self, messages: list[dict[str, object]]) -> None:
        chat = json.loads(self.chat.read_text(encoding="utf-8"))
        chat["messages"].extend(messages)
        self.chat.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_intake(
        self, *extra_arguments: object, expected_returncode: int = 0
    ) -> dict[str, Any] | None:
        result = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--scripted-clipboard",
            self.clipboard,
            "--fake-blog-directory",
            self.fake_blog,
            *extra_arguments,
        )
        self.assertEqual(result.returncode, expected_returncode, result.stderr)
        if expected_returncode != 0:
            return None
        return cast(dict[str, Any], json.loads(result.stdout))

    def write_blog_control(self, value: dict[str, object]) -> None:
        self.fake_blog.mkdir(parents=True, exist_ok=True)
        self.fake_blog.joinpath("control.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_interruption_after_registration_keeps_every_new_task_and_clears_clipboard(
        self,
    ) -> None:
        initialized = self.initialize()
        self.assertEqual(initialized["validation_scope"], "core_validated")
        self.assertEqual(
            self.clipboard_record(),
            {"schema_version": 1, "owner_id": None, "text": ""},
        )
        self.append_messages(
            [
                *submission("first", "author-first"),
                {
                    "message_id": "missing-target-header",
                    "kind": "text",
                    "text": "#投稿\n目标:",
                },
                {
                    "message_id": "missing-target-article",
                    "kind": "official_account_article",
                    "title": "Missing target",
                    "body": "Still retained as input evidence.",
                    "source_url": "https://example.com/missing-target",
                    "images": [],
                },
                *submission("third", "author-third"),
            ]
        )
        self.write_clipboard("another sensitive value")

        self.run_intake(
            "--simulate-interruption-after",
            "task_created",
            expected_returncode=2,
        )

        task_directories = sorted((self.repository / "tasks").iterdir())
        self.assertEqual(len(task_directories), 3)
        task_records = [
            json.loads(path.joinpath("task.json").read_text(encoding="utf-8"))
            for path in task_directories
        ]
        self.assertTrue(
            all(record["milestone"] == "task_created" for record in task_records)
        )
        self.assertEqual(
            sum(record["blocker"] is not None for record in task_records), 1
        )
        self.assertTrue(
            all(not path.joinpath("raw", "capture").exists() for path in task_directories)
        )
        chat = json.loads(self.chat.read_text(encoding="utf-8"))
        markers = [
            message for message in chat["messages"] if message["kind"] == "batch_marker"
        ]
        self.assertEqual(len(markers), 2)
        self.assertEqual(
            self.clipboard_record(),
            {"schema_version": 1, "owner_id": None, "text": ""},
        )

    def test_historical_work_runs_first_and_one_failure_does_not_stop_new_tasks(
        self,
    ) -> None:
        self.initialize()
        self.write_blog_control(
            {
                "create_draft_failures": [
                    {
                        "category": "transient",
                        "code": "first_timeout",
                        "message": "First request timed out",
                    }
                ]
            }
        )
        self.append_messages(submission("historical", "author-historical"))
        first = self.run_intake()
        assert first is not None
        historical_task_id = first["task_ids"][0]
        historical_path = self.repository / "tasks" / historical_task_id / "task.json"
        historical = json.loads(historical_path.read_text(encoding="utf-8"))
        self.assertEqual(historical["blocker"]["kind"], "retry_pending")

        self.write_blog_control(
            {
                "create_draft_responses": [
                    ["invalid response for the oldest task"]
                ]
            }
        )
        self.append_messages(
            [
                *submission("new", "author-new"),
                {
                    "message_id": "orphan-header",
                    "kind": "text",
                    "text": "#投稿\n目标: author-orphan",
                },
            ]
        )
        self.write_clipboard("must be discarded before the second run")

        second = self.run_intake()
        assert second is not None
        new_task_id, incomplete_task_id = second["task_ids"]

        self.assertEqual(
            second["attempted_task_ids"], [historical_task_id, new_task_id]
        )
        self.assertEqual(
            [result["task_id"] for result in second["task_results"]],
            [new_task_id, incomplete_task_id, historical_task_id],
        )
        self.assertEqual(
            {result["status"] for result in second["task_results"]},
            {"fake_draft_confirmed", "needs_input", "permanent_failure"},
        )
        completed_result = next(
            result
            for result in second["task_results"]
            if result["status"] == "fake_draft_confirmed"
        )
        self.assertEqual(
            completed_result["preview_url"],
            "https://blog.example.test/drafts/draft-000002",
        )
        failed_historical = json.loads(historical_path.read_text(encoding="utf-8"))
        self.assertEqual(failed_historical["blocker"]["kind"], "permanent_failure")
        completed_new = json.loads(
            (
                self.repository / "tasks" / new_task_id / "task.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(completed_new["milestone"], "draft_delivery_confirmed")
        self.assertEqual(
            self.clipboard_record(),
            {"schema_version": 1, "owner_id": None, "text": ""},
        )
        report = Path(second["report_path"]).read_text(encoding="utf-8")
        self.assertIn("Validation scope: core_validated", report)
        self.assertIn(historical_task_id, report)
        self.assertIn(str(completed_result["preview_url"]), report)
        chat = json.loads(self.chat.read_text(encoding="utf-8"))
        markers = [
            message for message in chat["messages"] if message["kind"] == "batch_marker"
        ]
        self.assertEqual(len(markers), 3)

    def test_run_refuses_clipboard_owned_by_another_desktop_session(self) -> None:
        self.initialize()
        self.append_messages(submission("blocked", "author-blocked"))
        self.write_clipboard("other session value", owner_id="other-desktop-session")
        marker_count_before = sum(
            message["kind"] == "batch_marker"
            for message in json.loads(self.chat.read_text(encoding="utf-8"))["messages"]
        )

        result = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--scripted-clipboard",
            self.clipboard,
            "--fake-blog-directory",
            self.fake_blog,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("scripted clipboard is already owned", result.stderr)
        self.assertEqual(
            self.clipboard_record()["owner_id"], "other-desktop-session"
        )
        marker_count_after = sum(
            message["kind"] == "batch_marker"
            for message in json.loads(self.chat.read_text(encoding="utf-8"))["messages"]
        )
        self.assertEqual(marker_count_after, marker_count_before)

    def test_status_reports_configurable_disk_warning_without_writing(self) -> None:
        self.initialize()
        before = {
            str(path.relative_to(self.repository)): path.read_bytes()
            for path in self.repository.rglob("*")
            if path.is_file()
        }

        result = run_cli(
            "status",
            "--repository",
            self.repository,
            "--disk-warning-bytes",
            1,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertGreater(status["disk_usage"]["bytes"], 1)
        self.assertEqual(status["disk_usage"]["warning_threshold_bytes"], 1)
        self.assertTrue(status["disk_usage"]["warning"])
        after = {
            str(path.relative_to(self.repository)): path.read_bytes()
            for path in self.repository.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
