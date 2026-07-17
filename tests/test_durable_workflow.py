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


class DurableWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.repository = root / "task-repository"
        self.chat = root / "scripted-chat.json"
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
            "initialize", "--repository", self.repository, "--scripted-chat", self.chat
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def append_submission(self, *, complete: bool = True) -> None:
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        article: dict[str, Any] = {
            "message_id": "article",
            "kind": "official_account_article",
            "title": "Durable workflow",
        }
        if complete:
            article.update(
                {
                    "body": "Every step has durable evidence.",
                    "source_url": "https://example.com/durable",
                    "images": [],
                }
            )
        else:
            article["scripted_capture"] = {
                "clipboard_text": "Incomplete capture.",
                "source_url": None,
                "article_end_observed": False,
                "all_static_images_captured": True,
                "media": [],
            }
        chat["messages"].extend(
            [
                {"message_id": "header", "kind": "text", "text": "#投稿\n目标: writer"},
                article,
            ]
        )
        self.chat.write_text(json.dumps(chat), encoding="utf-8")

    def run_intake(self, *extra: object) -> dict[str, Any]:
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

    def task(self, task_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                (self.repository / "tasks" / task_id / "task.json").read_text("utf-8")
            ),
        )

    def test_successful_content_task_commits_four_milestones(self) -> None:
        self.append_submission()
        result = self.run_intake()
        task_id = result["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        events = [
            json.loads(path.read_text("utf-8"))
            for path in sorted((task_directory / "events").glob("*.json"))
        ]

        self.assertEqual(self.task(task_id)["milestone"], "rewrite_artifact_ready")
        self.assertEqual(
            [
                event["milestone"]
                for event in events
                if event["type"] == "milestone_committed"
            ],
            [
                "task_created",
                "raw_evidence_ready",
                "structured_source_ready",
                "rewrite_artifact_ready",
            ],
        )
        self.assertEqual(
            [
                event["operation"]
                for event in events
                if event["type"] == "attempt_started"
            ],
            [
                "capture_raw_evidence",
                "build_structured_source",
                "generate_rewrite",
                "validate_rewrite_artifact",
            ],
        )
        self.assertEqual(
            [event["sequence"] for event in events], list(range(1, len(events) + 1))
        )

    def assert_resumes_after(self, milestone: str) -> None:
        self.append_submission()
        interrupted = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--simulate-interruption-after",
            milestone,
        )
        self.assertEqual(interrupted.returncode, 2)
        self.assertIn("Simulated interruption", interrupted.stderr)
        task_directory = next((self.repository / "tasks").iterdir())
        self.assertEqual(self.task(task_directory.name)["milestone"], milestone)

        recovered = self.run_intake()
        self.assertEqual(
            self.task(task_directory.name)["milestone"], "rewrite_artifact_ready"
        )
        if milestone == "rewrite_artifact_ready":
            self.assertNotIn(task_directory.name, recovered["attempted_task_ids"])
        else:
            self.assertIn(task_directory.name, recovered["attempted_task_ids"])

    def test_resume_after_task_created(self) -> None:
        self.assert_resumes_after("task_created")

    def test_resume_after_raw_evidence_ready(self) -> None:
        self.assert_resumes_after("raw_evidence_ready")

    def test_resume_after_structured_source_ready(self) -> None:
        self.assert_resumes_after("structured_source_ready")

    def test_completed_content_is_not_reprocessed(self) -> None:
        self.assert_resumes_after("rewrite_artifact_ready")

    def test_retry_exhaustion_requires_explicit_retry(self) -> None:
        self.append_submission(complete=False)
        first = self.run_intake()
        task_id = first["task_ids"][0]
        self.assertEqual(self.task(task_id)["blocker"]["kind"], "retry_pending")

        second = self.run_intake()
        self.assertIn(task_id, second["attempted_task_ids"])
        self.assertEqual(self.task(task_id)["blocker"]["kind"], "retry_exhausted")
        skipped = self.run_intake()
        self.assertNotIn(task_id, skipped["attempted_task_ids"])

        enabled = run_cli(
            "retry", "--repository", self.repository, "--task-id", task_id
        )
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertEqual(self.task(task_id)["blocker"]["kind"], "retry_pending")

    def test_status_rejects_unknown_task_fields(self) -> None:
        self.append_submission()
        result = self.run_intake()
        task_id = result["task_ids"][0]
        path = self.repository / "tasks" / task_id / "task.json"
        task = self.task(task_id)
        task["unexpected"] = True
        path.write_text(json.dumps(task), encoding="utf-8")

        status = run_cli("status", "--repository", self.repository)
        self.assertEqual(status.returncode, 2)
        self.assertIn("unknown fields", status.stderr)


if __name__ == "__main__":
    unittest.main()
