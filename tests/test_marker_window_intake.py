from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


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


def header(message_id: str, target: str) -> dict[str, object]:
    return {
        "message_id": message_id,
        "kind": "text",
        "text": f"#投稿\n目标: {target}",
    }


def article(message_id: str, title: str) -> dict[str, object]:
    return {
        "message_id": message_id,
        "kind": "official_account_article",
        "title": title,
        "body": f"{title}的正文。",
        "source_url": f"https://example.com/{message_id}",
        "images": [],
    }


class MarkerWindowIntakeTest(unittest.TestCase):
    def test_initialize_sets_a_baseline_and_run_excludes_messages_after_its_marker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "task-repository"
            chat_path = root / "scripted-chat.json"
            fake_blog = root / "fake-blog"
            chat: dict[str, Any] = {
                "schema_version": 1,
                "conversation": "file-transfer-assistant",
                "messages": [
                    header("history-header", "ignored-history"),
                    article("history-article", "初始化前的历史文章"),
                ],
                "arrive_after_next_marker": [],
            }
            chat_path.write_text(
                json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            initialized = run_cli(
                "initialize",
                "--repository",
                repository,
                "--scripted-chat",
                chat_path,
            )

            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            initialize_result = json.loads(initialized.stdout)
            baseline_marker_id = initialize_result["baseline_marker_id"]

            chat = json.loads(chat_path.read_text("utf-8"))
            chat["messages"].extend(
                [
                    header("new-header", "author-new"),
                    article("new-article", "本次应处理的文章"),
                ]
            )
            chat["arrive_after_next_marker"] = [
                header("late-header", "author-late"),
                article("late-article", "下一次才处理的文章"),
            ]
            chat_path.write_text(
                json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            completed = run_cli(
                "run",
                "--repository",
                repository,
                "--scripted-chat",
                chat_path,
                "--fake-blog-directory",
                fake_blog,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(len(result["task_ids"]), 1)
            run_id = result["run_id"]
            task_id = result["task_ids"][0]
            run = json.loads(
                (repository / "runs" / run_id / "run.json").read_text("utf-8")
            )
            raw = json.loads(
                (repository / "tasks" / task_id / "raw" / "submission.json").read_text(
                    "utf-8"
                )
            )
            task_directory = repository / "tasks" / task_id
            rewrite = (task_directory / "rewrite" / "content.md").read_text("utf-8")
            delivery_request = json.loads(
                (task_directory / "delivery" / "request.json").read_text("utf-8")
            )
            delivery_response = json.loads(
                (task_directory / "delivery" / "response.json").read_text("utf-8")
            )
            report = (repository / "runs" / run_id / "report.md").read_text("utf-8")

            self.assertEqual(run["input_window"]["previous_marker_id"], baseline_marker_id)
            self.assertEqual(run["input_window"]["current_marker_id"], result["marker_id"])
            self.assertEqual(raw["article"]["title"], "本次应处理的文章")
            self.assertIn("本次应处理的文章", rewrite)
            self.assertEqual(delivery_request["idempotency_key"], task_id)
            self.assertEqual(delivery_response["status"], "accepted")
            self.assertIn(task_id, report)

            final_chat = json.loads(chat_path.read_text("utf-8"))
            marker_indexes = [
                index
                for index, message in enumerate(final_chat["messages"])
                if message["kind"] == "batch_marker"
            ]
            self.assertEqual(len(marker_indexes), 2)
            current_marker_index = marker_indexes[-1]
            self.assertEqual(
                final_chat["messages"][current_marker_index + 1]["message_id"],
                "late-header",
            )

            next_run = run_cli(
                "run",
                "--repository",
                repository,
                "--scripted-chat",
                chat_path,
                "--fake-blog-directory",
                fake_blog,
            )
            self.assertEqual(next_run.returncode, 0, next_run.stderr)
            next_result = json.loads(next_run.stdout)
            next_raw = json.loads(
                (
                    repository
                    / "tasks"
                    / next_result["task_ids"][0]
                    / "raw"
                    / "submission.json"
                ).read_text("utf-8")
            )
            self.assertEqual(next_raw["article"]["title"], "下一次才处理的文章")

    def test_run_accepts_minimal_and_multiline_headers_and_isolates_unknown_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "task-repository"
            chat_path = root / "scripted-chat.json"
            fake_blog = root / "fake-blog"
            chat_path.write_text(
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
                repository,
                "--scripted-chat",
                chat_path,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            chat = json.loads(chat_path.read_text("utf-8"))
            chat["messages"].extend(
                [
                    header("default-header", "author-default"),
                    article("default-article", "省略要求"),
                    {
                        "message_id": "empty-header",
                        "kind": "text",
                        "text": "#投稿\n目标: author-empty\n要求:",
                    },
                    article("empty-article", "空要求"),
                    {
                        "message_id": "multiline-header",
                        "kind": "text",
                        "text": (
                            "#投稿\n目标: author-custom\n文章数: 1\n要求:\n"
                            "突出恢复能力\n不要添加来源中没有的事实"
                        ),
                    },
                    article("multiline-article", "多行要求"),
                    {
                        "message_id": "unknown-header",
                        "kind": "text",
                        "text": "#投稿\n目标: author-unknown\n作者: 不应接受",
                    },
                    article("unknown-article", "未知字段"),
                    {
                        "message_id": "multi-source-header",
                        "kind": "text",
                        "text": "#投稿\n目标: author-multi\n文章数: 2",
                    },
                    article("multi-source-article", "暂不支持多文章"),
                    {
                        "message_id": "duplicate-field-header",
                        "kind": "text",
                        "text": "#投稿\n目标: first\n目标: second",
                    },
                    article("duplicate-field-article", "重复控制字段"),
                ]
            )
            chat_path.write_text(
                json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            completed = run_cli(
                "run",
                "--repository",
                repository,
                "--scripted-chat",
                chat_path,
                "--fake-blog-directory",
                fake_blog,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(len(result["task_ids"]), 6)
            self.assertEqual(
                [item["status"] for item in result["task_results"]],
                [
                    "fake_draft_confirmed",
                    "fake_draft_confirmed",
                    "fake_draft_confirmed",
                    "needs_input",
                    "needs_input",
                    "needs_input",
                ],
            )

            task_records = [
                json.loads(
                    (repository / "tasks" / task_id / "task.json").read_text("utf-8")
                )
                for task_id in result["task_ids"]
            ]
            self.assertIsNone(task_records[0]["requirements"])
            self.assertIsNone(task_records[1]["requirements"])
            self.assertEqual(
                task_records[2]["requirements"],
                "突出恢复能力\n不要添加来源中没有的事实",
            )
            self.assertEqual(task_records[3]["blocker"]["reason"], "unknown_control_field")
            self.assertEqual(
                task_records[4]["blocker"]["reason"], "unsupported_article_count"
            )
            self.assertEqual(
                task_records[5]["blocker"]["reason"], "duplicate_control_field"
            )
            self.assertEqual(len(list((fake_blog / "drafts").glob("*.json"))), 3)

    def test_invalid_inputs_are_isolated_and_identical_submissions_remain_distinct(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "task-repository"
            chat_path = root / "scripted-chat.json"
            fake_blog = root / "fake-blog"
            chat_path.write_text(
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
                repository,
                "--scripted-chat",
                chat_path,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            duplicate_header = {
                "kind": "text",
                "text": "#投稿\n目标: author-duplicate",
            }
            duplicate_article = {
                "kind": "official_account_article",
                "title": "完全相同的投稿",
                "body": "相同正文。",
                "source_url": "https://example.com/duplicate",
                "images": [],
            }
            chat = json.loads(chat_path.read_text("utf-8"))
            chat["messages"].extend(
                [
                    {
                        "message_id": "missing-target-header",
                        "kind": "text",
                        "text": "#投稿\n目标:",
                    },
                    article("missing-target-article", "缺少目标"),
                    header("unsupported-header", "author-file"),
                    {
                        "message_id": "unsupported-file",
                        "kind": "file",
                        "name": "source.pdf",
                    },
                    article("bare-article", "没有任务头的裸转发"),
                    header("orphan-header", "author-orphan"),
                    {"message_id": "duplicate-header-1", **duplicate_header},
                    {"message_id": "duplicate-article-1", **duplicate_article},
                    {"message_id": "duplicate-header-2", **duplicate_header},
                    {"message_id": "duplicate-article-2", **duplicate_article},
                ]
            )
            chat_path.write_text(
                json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            completed = run_cli(
                "run",
                "--repository",
                repository,
                "--scripted-chat",
                chat_path,
                "--fake-blog-directory",
                fake_blog,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                [item["status"] for item in result["task_results"]],
                [
                    "needs_input",
                    "needs_input",
                    "needs_input",
                    "needs_input",
                    "fake_draft_confirmed",
                    "fake_draft_confirmed",
                ],
            )
            self.assertEqual(
                [
                    item["blocker_reason"]
                    for item in result["task_results"]
                    if item["status"] == "needs_input"
                ],
                [
                    "missing_target",
                    "unsupported_source_type",
                    "missing_task_header",
                    "missing_adjacent_article",
                ],
            )
            duplicate_task_ids = result["task_ids"][-2:]
            self.assertNotEqual(duplicate_task_ids[0], duplicate_task_ids[1])
            duplicate_raw = [
                json.loads(
                    (
                        repository
                        / "tasks"
                        / task_id
                        / "raw"
                        / "submission.json"
                    ).read_text("utf-8")
                )
                for task_id in duplicate_task_ids
            ]
            self.assertEqual(duplicate_raw[0]["article"], duplicate_raw[1]["article"])
            self.assertEqual(len(list((fake_blog / "drafts").glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
