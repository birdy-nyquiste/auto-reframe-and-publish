from __future__ import annotations

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


class DurableWorkflowTest(unittest.TestCase):
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

    def append_submission(self, target: str = "author-durable") -> None:
        chat = json.loads(self.chat.read_text("utf-8"))
        chat["messages"].extend(
            [
                {
                    "message_id": "durable-header",
                    "kind": "text",
                    "text": f"#投稿\n目标: {target}",
                },
                {
                    "message_id": "durable-article",
                    "kind": "official_account_article",
                    "title": "持久工作流",
                    "body": "每一步都先留下可以恢复的证据。",
                    "source_url": "https://example.com/durable",
                    "images": [],
                },
            ]
        )
        self.chat.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def write_blog_failures(self, categories: list[str]) -> None:
        self.fake_blog.mkdir(parents=True, exist_ok=True)
        self.fake_blog.joinpath("control.json").write_text(
            json.dumps(
                {
                    "create_draft_failures": [
                        {
                            "category": category,
                            "code": f"fixture_{category}",
                            "message": f"Injected {category} failure",
                        }
                        for category in categories
                    ]
                }
            ),
            encoding="utf-8",
        )

    def run_intake(self, *extra_arguments: object) -> dict[str, Any]:
        completed = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
            *extra_arguments,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return cast(dict[str, Any], json.loads(completed.stdout))

    def test_successful_task_commits_five_milestones_and_attempt_events(self) -> None:
        self.append_submission()

        result = self.run_intake()

        run_id = result["run_id"]
        task_id = result["task_ids"][0]
        task_directory = self.repository / "tasks" / task_id
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        events = [
            json.loads(path.read_text("utf-8"))
            for path in sorted((task_directory / "events").glob("*.json"))
        ]

        self.assertEqual(task["milestone"], "draft_delivery_confirmed")
        self.assertEqual(
            [event["milestone"] for event in events if event["type"] == "milestone_committed"],
            [
                "task_created",
                "raw_evidence_ready",
                "structured_source_ready",
                "rewrite_artifact_ready",
                "draft_delivery_confirmed",
            ],
        )
        self.assertEqual(
            [event["operation"] for event in events if event["type"] == "attempt_started"],
            [
                "capture_raw_evidence",
                "build_structured_source",
                "generate_rewrite",
                "validate_rewrite_artifact",
                "deliver_draft",
            ],
        )
        self.assertTrue(all(event["run_id"] == run_id for event in events))
        self.assertEqual(
            [event["sequence"] for event in events],
            list(range(1, len(events) + 1)),
        )
        milestone_events = [
            event for event in events if event["type"] == "milestone_committed"
        ]
        self.assertTrue(
            all(
                event["state_after"]["milestone"] == event["milestone"]
                for event in milestone_events
            )
        )

    def assert_next_run_resumes_after(self, milestone: str) -> None:
        self.append_submission("author-recovery")

        interrupted = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
            "--simulate-interruption-after",
            milestone,
        )

        self.assertEqual(interrupted.returncode, 2)
        self.assertIn("Simulated interruption", interrupted.stderr)
        interrupted_runs = [
            path
            for path in (self.repository / "runs").iterdir()
            if json.loads((path / "run.json").read_text("utf-8"))["status"]
            == "interrupted"
        ]
        self.assertEqual(len(interrupted_runs), 1)
        self.assertIn(
            "Status: interrupted",
            (interrupted_runs[0] / "report.md").read_text("utf-8"),
        )
        task_directories = list((self.repository / "tasks").iterdir())
        self.assertEqual(len(task_directories), 1)
        task_directory = task_directories[0]
        interrupted_task = json.loads(
            (task_directory / "task.json").read_text("utf-8")
        )
        self.assertEqual(interrupted_task["milestone"], milestone)

        recovered = self.run_intake()

        recovered_task = json.loads((task_directory / "task.json").read_text("utf-8"))
        events = [
            json.loads(path.read_text("utf-8"))
            for path in sorted((task_directory / "events").glob("*.json"))
        ]
        self.assertEqual(recovered_task["milestone"], "draft_delivery_confirmed")
        if milestone == "draft_delivery_confirmed":
            self.assertNotIn(task_directory.name, recovered["attempted_task_ids"])
        else:
            self.assertIn(task_directory.name, recovered["attempted_task_ids"])
        self.assertEqual(len(list((self.fake_blog / "drafts").glob("*.json"))), 1)
        self.assertEqual(
            [
                event["milestone"]
                for event in events
                if event["type"] == "milestone_committed"
            ].count(milestone),
            1,
        )

    def test_next_run_resumes_after_task_creation(self) -> None:
        self.assert_next_run_resumes_after("task_created")

    def test_next_run_resumes_after_raw_evidence(self) -> None:
        self.assert_next_run_resumes_after("raw_evidence_ready")

    def test_next_run_resumes_after_structured_source(self) -> None:
        self.assert_next_run_resumes_after("structured_source_ready")

    def test_next_run_resumes_after_rewrite_artifact(self) -> None:
        self.assert_next_run_resumes_after("rewrite_artifact_ready")

    def test_next_run_does_not_redeliver_after_confirmed_draft(self) -> None:
        self.assert_next_run_resumes_after("draft_delivery_confirmed")

    def test_retry_exhaustion_requires_explicit_retry_before_success(self) -> None:
        self.write_blog_failures(["transient", "transient"])
        self.append_submission("author-retry")

        first_run = self.run_intake()
        task_id = first_run["task_ids"][0]
        task_path = self.repository / "tasks" / task_id / "task.json"
        first_task = json.loads(task_path.read_text("utf-8"))
        self.assertEqual(first_task["milestone"], "rewrite_artifact_ready")
        self.assertEqual(first_task["blocker"]["kind"], "retry_pending")
        self.assertEqual(first_task["blocker"]["attempts_used"], 1)

        second_run = self.run_intake()
        second_task = json.loads(task_path.read_text("utf-8"))
        self.assertIn(task_id, second_run["attempted_task_ids"])
        self.assertEqual(second_task["blocker"]["kind"], "retry_exhausted")
        self.assertEqual(second_task["blocker"]["attempts_used"], 2)

        # Emulate a crash after the authoritative failure event but before its
        # task.json projection was replaced.
        task_path.write_text(
            json.dumps(first_task, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        skipped_run = self.run_intake()
        self.assertNotIn(task_id, skipped_run["attempted_task_ids"])
        projected_exhausted = json.loads(task_path.read_text("utf-8"))
        self.assertEqual(projected_exhausted["blocker"]["kind"], "retry_exhausted")

        enabled = run_cli(
            "retry",
            "--repository",
            self.repository,
            "--task-id",
            task_id,
        )
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        enabled_result = json.loads(enabled.stdout)
        self.assertEqual(enabled_result["status"], "retry_enabled")
        enabled_task = json.loads(task_path.read_text("utf-8"))
        self.assertEqual(enabled_task["blocker"]["kind"], "retry_pending")
        self.assertEqual(enabled_task["blocker"]["attempts_used"], 0)
        self.assertEqual(enabled_task["retry_generation"], 1)

        # Emulate the same projection gap after the explicit retry event.
        task_path.write_text(
            json.dumps(second_task, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        completed_run = self.run_intake()
        completed_task = json.loads(task_path.read_text("utf-8"))
        self.assertIn(task_id, completed_run["attempted_task_ids"])
        self.assertEqual(completed_task["milestone"], "draft_delivery_confirmed")
        self.assertIsNone(completed_task["blocker"])
        self.assertEqual(len(list((self.fake_blog / "drafts").glob("*.json"))), 1)

    def test_permanent_failure_is_not_retried_by_run_or_retry(self) -> None:
        self.write_blog_failures(["permanent"])
        self.append_submission("author-permanent")

        first_run = self.run_intake()
        task_id = first_run["task_ids"][0]
        task_path = self.repository / "tasks" / task_id / "task.json"
        failed_task = json.loads(task_path.read_text("utf-8"))
        self.assertEqual(failed_task["blocker"]["kind"], "permanent_failure")

        skipped_run = self.run_intake()
        self.assertNotIn(task_id, skipped_run["attempted_task_ids"])
        rejected_retry = run_cli(
            "retry",
            "--repository",
            self.repository,
            "--task-id",
            task_id,
        )
        self.assertEqual(rejected_retry.returncode, 2)
        self.assertIn("is not retry_exhausted", rejected_retry.stderr)

    def test_status_is_read_only_and_mutations_refuse_an_existing_writer_lock(
        self,
    ) -> None:
        lock = {
            "schema_version": 1,
            "owner_id": "stale-fixture-owner",
            "pid": 999999,
            "host": "fixture-host",
            "operation": "run",
            "started_at": "2000-01-01T00:00:00+00:00",
        }
        lock_path = self.repository / "writer.lock"
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        before = self.repository_snapshot()

        status = run_cli("status", "--repository", self.repository)

        self.assertEqual(status.returncode, 0, status.stderr)
        status_result = json.loads(status.stdout)
        self.assertEqual(status_result["writer_lock"]["owner_id"], "stale-fixture-owner")
        self.assertFalse(status_result["writer_lock"]["automatic_reclaim"])
        self.assertEqual(self.repository_snapshot(), before)

        refused = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--fake-blog-directory",
            self.fake_blog,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("writer lock is already held", refused.stderr)
        self.assertTrue(lock_path.exists())
        self.assertEqual(
            json.loads(lock_path.read_text("utf-8"))["owner_id"],
            "stale-fixture-owner",
        )

    def repository_snapshot(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.repository)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(self.repository.rglob("*"))
            if path.is_file()
        }

    def test_status_rejects_unknown_fields_and_illegal_task_combinations(self) -> None:
        self.append_submission("author-schema")
        result = self.run_intake()
        task_path = self.repository / "tasks" / result["task_ids"][0] / "task.json"
        task = json.loads(task_path.read_text("utf-8"))
        task["unknown_field"] = "must be rejected"
        task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")

        unknown = run_cli("status", "--repository", self.repository)
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("unknown fields", unknown.stderr)

        task.pop("unknown_field")
        task["blocker"] = {
            "kind": "retry_pending",
            "operation": "deliver_draft",
            "error_category": "transient",
            "error_code": "fixture",
            "attempts_used": 1,
            "retry_budget": 2,
            "retry_generation": 0,
        }
        task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")

        illegal = run_cli("status", "--repository", self.repository)
        self.assertEqual(illegal.returncode, 2)
        self.assertIn("illegal blocker", illegal.stderr)

        task["blocker"] = None
        task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
        run_path = self.repository / "runs" / result["run_id"] / "run.json"
        run = json.loads(run_path.read_text("utf-8"))
        run["completed_at"] = None
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

        illegal_run = run_cli("status", "--repository", self.repository)
        self.assertEqual(illegal_run.returncode, 2)
        self.assertIn("completed_at must be string", illegal_run.stderr)

    def test_schema_rejects_contradictory_retry_counts_and_generations(self) -> None:
        self.append_submission("author-retry-schema")
        result = self.run_intake()
        task_path = self.repository / "tasks" / result["task_ids"][0] / "task.json"
        task = json.loads(task_path.read_text("utf-8"))
        task["milestone"] = "rewrite_artifact_ready"
        task["external_draft"] = None
        task["blocker"] = {
            "kind": "retry_pending",
            "operation": "deliver_draft",
            "error_category": "transient",
            "error_code": "fixture",
            "attempts_used": 2,
            "retry_budget": 2,
            "retry_generation": 0,
        }
        task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")

        pending_at_budget = run_cli("status", "--repository", self.repository)
        self.assertEqual(pending_at_budget.returncode, 2)
        self.assertIn("must be below retry_budget", pending_at_budget.stderr)

        task["blocker"]["kind"] = "retry_exhausted"
        task["blocker"]["attempts_used"] = 1
        task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
        exhausted_below_budget = run_cli("status", "--repository", self.repository)
        self.assertEqual(exhausted_below_budget.returncode, 2)
        self.assertIn("must equal retry_budget", exhausted_below_budget.stderr)

        task["blocker"]["attempts_used"] = 2
        task["blocker"]["retry_generation"] = 1
        task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
        mismatched_generation = run_cli("status", "--repository", self.repository)
        self.assertEqual(mismatched_generation.returncode, 2)
        self.assertIn("must match task retry_generation", mismatched_generation.stderr)

    def test_next_run_rebuilds_task_and_raw_projections_from_committed_events(self) -> None:
        self.append_submission("author-wal-recovery")
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
        self.assertEqual(interrupted.returncode, 2)
        task_directory = next((self.repository / "tasks").iterdir())
        (task_directory / "task.json").unlink()
        (task_directory / "raw" / "intake.json").unlink()
        before_status = self.repository_snapshot()

        status = run_cli("status", "--repository", self.repository)

        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(self.repository_snapshot(), before_status)
        self.assertFalse((task_directory / "task.json").exists())
        self.assertFalse((task_directory / "raw" / "intake.json").exists())

        recovered = self.run_intake()

        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        self.assertEqual(task["milestone"], "draft_delivery_confirmed")
        self.assertTrue((task_directory / "raw" / "intake.json").exists())
        self.assertIn(task_directory.name, recovered["attempted_task_ids"])

    def test_next_run_recovers_a_processing_run_left_by_a_crashed_process(self) -> None:
        self.append_submission("author-crash-recovery")
        first = self.run_intake()
        previous_run_path = self.repository / "runs" / first["run_id"] / "run.json"
        previous_run = json.loads(previous_run_path.read_text("utf-8"))
        previous_run["status"] = "processing"
        previous_run["completed_at"] = None
        previous_run["recovered_by_run"] = None
        previous_run_path.write_text(
            json.dumps(previous_run, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        recovered = self.run_intake()

        recovered_previous = json.loads(previous_run_path.read_text("utf-8"))
        self.assertEqual(recovered_previous["status"], "interrupted")
        self.assertEqual(recovered_previous["recovered_by_run"], recovered["run_id"])
        previous_report = previous_run_path.with_name("report.md").read_text("utf-8")
        self.assertIn(f"Recovered by run: {recovered['run_id']}", previous_report)
        current_report = Path(recovered["report_path"]).read_text("utf-8")
        self.assertIn(f"Recovered runs: {first['run_id']}", current_report)

    def test_pending_window_reuses_durable_run_and_task_ids_before_cursor_advance(
        self,
    ) -> None:
        self.append_submission("author-pending-window")
        chat = json.loads(self.chat.read_text("utf-8"))
        marker_id = "marker-crash-window"
        chat["messages"].append(
            {
                "message_id": marker_id,
                "kind": "batch_marker",
                "marker_id": marker_id,
                "text": f"#批次 {marker_id}",
                "sent_at": "2026-07-15T00:00:00+00:00",
            }
        )
        self.chat.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        metadata_path = self.repository / "repository.json"
        metadata = json.loads(metadata_path.read_text("utf-8"))
        previous_marker = metadata["intake"]["last_marker_id"]
        metadata["pending_window"] = {
            "adapter": "scripted_chat",
            "conversation": "file-transfer-assistant",
            "previous_marker_id": previous_marker,
            "current_marker_id": marker_id,
            "messages": chat["messages"][-3:-1],
            "run_id": "run-pending-fixture",
            "task_ids": ["task-pending-fixture"],
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        result = self.run_intake()

        updated_metadata = json.loads(metadata_path.read_text("utf-8"))
        self.assertEqual(result["run_id"], "run-pending-fixture")
        self.assertEqual(result["task_ids"], ["task-pending-fixture"])
        self.assertEqual(result["marker_id"], marker_id)
        self.assertEqual(updated_metadata["intake"]["last_marker_id"], marker_id)
        self.assertIsNone(updated_metadata["pending_window"])

    def test_run_recovers_a_marker_sent_before_its_window_was_journaled(self) -> None:
        self.append_submission("author-orphan-marker")
        chat = json.loads(self.chat.read_text("utf-8"))
        marker_id = "marker-before-journal-crash"
        chat["messages"].append(
            {
                "message_id": marker_id,
                "kind": "batch_marker",
                "marker_id": marker_id,
                "text": f"#批次 {marker_id}",
                "sent_at": "2026-07-15T00:00:00+00:00",
            }
        )
        self.chat.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        marker_count_before = sum(
            message.get("kind") == "batch_marker" for message in chat["messages"]
        )

        result = self.run_intake()

        updated_chat = json.loads(self.chat.read_text("utf-8"))
        marker_count_after = sum(
            message.get("kind") == "batch_marker"
            for message in updated_chat["messages"]
        )
        self.assertEqual(result["marker_id"], marker_id)
        self.assertEqual(marker_count_after, marker_count_before)
        self.assertEqual(result["task_results"][0]["status"], "fake_draft_confirmed")

    def test_event_chain_rejects_a_schema_valid_milestone_regression(self) -> None:
        self.append_submission("author-event-chain")
        result = self.run_intake()
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        task["milestone"] = "rewrite_artifact_ready"
        task["external_draft"] = None
        event_paths = sorted((task_directory / "events").glob("*.json"))
        sequence = len(event_paths) + 1
        event_id = "event-regression-fixture"
        regression = {
            "schema_version": 2,
            "event_id": event_id,
            "sequence": sequence,
            "task_id": task["task_id"],
            "run_id": result["run_id"],
            "occurred_at": "2026-07-15T00:00:00+00:00",
            "type": "milestone_committed",
            "milestone": "rewrite_artifact_ready",
            "operation": None,
            "outcome": None,
            "details": {},
            "state_after": task,
        }
        regression_path = task_directory / "events" / f"{sequence:06d}-{event_id}.json"
        regression_path.write_text(
            json.dumps(regression, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        status = run_cli("status", "--repository", self.repository)

        self.assertEqual(status.returncode, 2)
        self.assertIn("Illegal task event transition", status.stderr)

    def test_event_chain_rejects_retry_enabled_from_permanent_failure(self) -> None:
        self.write_blog_failures(["permanent"])
        self.append_submission("author-illegal-retry-event")
        result = self.run_intake()
        task_directory = self.repository / "tasks" / result["task_ids"][0]
        task = json.loads((task_directory / "task.json").read_text("utf-8"))
        previous_blocker = task["blocker"]
        task["retry_generation"] = 1
        task["blocker"] = {
            "kind": "retry_pending",
            "operation": "deliver_draft",
            "error_category": "permanent",
            "error_code": previous_blocker["error_code"],
            "attempts_used": 0,
            "retry_budget": 2,
            "retry_generation": 1,
        }
        event_paths = sorted((task_directory / "events").glob("*.json"))
        sequence = len(event_paths) + 1
        event_id = "event-illegal-retry-fixture"
        illegal_retry = {
            "schema_version": 2,
            "event_id": event_id,
            "sequence": sequence,
            "task_id": task["task_id"],
            "run_id": result["run_id"],
            "occurred_at": "2026-07-15T00:00:00+00:00",
            "type": "retry_enabled",
            "milestone": None,
            "operation": "deliver_draft",
            "outcome": "enabled",
            "details": {},
            "state_after": task,
        }
        event_path = task_directory / "events" / f"{sequence:06d}-{event_id}.json"
        event_path.write_text(
            json.dumps(illegal_retry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        status = run_cli("status", "--repository", self.repository)

        self.assertEqual(status.returncode, 2)
        self.assertIn(
            "retry_enabled requires retry_exhausted -> retry_pending", status.stderr
        )


if __name__ == "__main__":
    unittest.main()
