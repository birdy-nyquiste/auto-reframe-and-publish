from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/process-weixin-submissions/scripts/process_weixin_submissions.py"
FIXTURE = ROOT / "tests/fixtures/standard-submission.json"


class ScriptedSubmissionTest(unittest.TestCase):
    def test_operator_can_create_a_fake_blog_draft_from_scripted_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "task-repository"
            fake_blog = Path(temporary_directory) / "fake-blog"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "run",
                    "--repository",
                    str(repository),
                    "--input",
                    str(FIXTURE),
                    "--blog-adapter",
                    "fake",
                    "--fake-blog-directory",
                    str(fake_blog),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            run_id = result["run_id"]
            task_id = result["task_ids"][0]

            run = json.loads(
                (repository / "runs" / run_id / "run.json").read_text("utf-8")
            )
            task_directory = repository / "tasks" / task_id
            task = json.loads((task_directory / "task.json").read_text("utf-8"))
            rewrite = (task_directory / "rewrite" / "content.md").read_text("utf-8")
            rewrite_manifest = json.loads(
                (task_directory / "rewrite" / "manifest.json").read_text("utf-8")
            )
            delivery_request = json.loads(
                (task_directory / "delivery" / "request.json").read_text("utf-8")
            )
            delivery_response = json.loads(
                (task_directory / "delivery" / "response.json").read_text("utf-8")
            )
            fake_blog_draft = json.loads(
                (fake_blog / "drafts" / "draft-000001.json").read_text("utf-8")
            )
            report = (repository / "runs" / run_id / "report.md").read_text("utf-8")

            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["created_task_ids"], [task_id])
            self.assertEqual(run["attempted_task_ids"], [task_id])
            self.assertEqual(task["milestone"], "external_draft_confirmed")
            self.assertEqual(task["target_id"], "author-nyquist")
            self.assertEqual(task["external_draft"]["draft_id"], "draft-000001")
            self.assertIn("让复杂工作流保持可恢复", rewrite)
            self.assertEqual(rewrite_manifest["artifact_kind"], "placeholder_rewrite")
            self.assertEqual(delivery_request["idempotency_key"], task_id)
            self.assertEqual(delivery_response["status"], "accepted")
            self.assertEqual(fake_blog_draft["request"], delivery_request)
            self.assertEqual(fake_blog_draft["response"], delivery_response)
            self.assertIn(run_id, report)
            self.assertIn(task_id, report)
            self.assertIn("draft-000001", report)

    def test_skill_cli_exposes_the_four_planned_operations(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        for operation in ("initialize", "run", "status", "retry"):
            self.assertIn(operation, completed.stdout)


if __name__ == "__main__":
    unittest.main()
