from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class LocalBlog:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.posts: dict[str, dict[str, Any]] = {}
        self.requests: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                slug = self.path.rsplit("/", 1)[-1]
                owner.requests.append({"method": "GET", "path": self.path})
                post = owner.posts.get(slug)
                if post is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self._json(200, {**post, "slug": slug, "url": owner.public_url(slug)})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "payload": payload,
                    }
                )
                if owner.mode == "reject":
                    self._json(400, {"message": "Payload was rejected"})
                    return
                if owner.mode == "conflict_disconnect":
                    owner.posts[payload["slug"]] = {
                        **payload,
                        "content": "Different content under the same slug",
                    }
                if owner.mode == "disconnect":
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                if owner.mode == "conflict_disconnect":
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                owner.posts[payload["slug"]] = payload
                self._json(
                    201,
                    {
                        "ok": True,
                        "slug": payload["slug"],
                        "url": owner.public_url(payload["slug"]),
                        "item": {"kind": "external", "slug": payload["slug"]},
                    },
                )

            def _json(self, status: int, value: dict[str, Any]) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{str(host)}:{port}/api/v1"

    def public_url(self, slug: str) -> str:
        return f"{self.base_url.removesuffix('/api/v1')}/posts/{slug}"

    def __enter__(self) -> "LocalBlog":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class LsforumPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.chat = self.root / "chat.json"
        self.config = self.root / "blog-config.json"
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
        result = run_cli(
            "initialize", "--repository", self.repository, "--scripted-chat", self.chat
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.old_key = os.environ.get("LSFORUM_TEST_KEY")
        os.environ["LSFORUM_TEST_KEY"] = "super-secret-test-key"

    def tearDown(self) -> None:
        if self.old_key is None:
            os.environ.pop("LSFORUM_TEST_KEY", None)
        else:
            os.environ["LSFORUM_TEST_KEY"] = self.old_key
        self.temporary_directory.cleanup()

    def append_submission(self) -> None:
        chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
        chat["messages"].extend(
            [
                {"message_id": "h", "kind": "text", "text": "#投稿\n目标: writer-one"},
                {
                    "message_id": "a",
                    "kind": "official_account_article",
                    "title": "A title",
                    "body": "Copied source body.",
                    "source_url": "https://example.com/source",
                    "images": [],
                },
            ]
        )
        self.chat.write_text(json.dumps(chat), encoding="utf-8")

    def write_config(self, blog: LocalBlog) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": blog.base_url,
                    "api_key_env": "LSFORUM_TEST_KEY",
                    "targets": {
                        "writer-one": {
                            "authorName": "Writer One",
                            "category": "Community",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def run_auto(self) -> dict[str, Any]:
        result = run_cli(
            "run",
            "--repository",
            self.repository,
            "--scripted-chat",
            self.chat,
            "--publication",
            "auto",
            "--blog-config",
            self.config,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return cast(dict[str, Any], json.loads(result.stdout))

    def test_http_adapter_maps_target_and_persists_no_secret(self) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            result = self.run_auto()

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "publication_confirmed")
        posts = [request for request in blog.requests if request["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["authorization"], "Bearer super-secret-test-key")
        self.assertEqual(posts[0]["payload"]["authorName"], "Writer One")
        self.assertEqual(posts[0]["payload"]["category"], "Community")
        self.assertIn("content", posts[0]["payload"])
        for path in self.repository.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"super-secret-test-key", path.read_bytes())

    def test_unknown_post_outcome_is_not_automatically_reposted(self) -> None:
        with LocalBlog(mode="disconnect") as blog:
            self.write_config(blog)
            self.append_submission()
            first = self.run_auto()
            second = self.run_auto()

        publication = first["publication_results"][0]
        self.assertEqual(publication["status"], "outcome_unknown")
        self.assertEqual(publication["blocker_reason"], "publication_outcome_unknown")
        self.assertEqual(second["publication_results"], [])
        self.assertEqual(
            len([request for request in blog.requests if request["method"] == "POST"]),
            1,
        )

    def test_explicit_http_rejection_preserves_raw_response(self) -> None:
        with LocalBlog(mode="reject") as blog:
            self.write_config(blog)
            self.append_submission()
            result = self.run_auto()

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "permanent_failure")
        raw = json.loads(
            (
                self.repository
                / "publications"
                / publication["publication_id"]
                / "attempts"
                / result["run_id"]
                / "response-raw.json"
            ).read_text("utf-8")
        )
        self.assertEqual(raw["http_status"], 400)
        self.assertEqual(raw["body"]["message"], "Payload was rejected")

    def test_recovery_refuses_same_title_with_different_body(self) -> None:
        with LocalBlog(mode="conflict_disconnect") as blog:
            self.write_config(blog)
            self.append_submission()
            result = self.run_auto()

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "outcome_unknown")
        self.assertEqual(publication["blocker_reason"], "publication_outcome_unknown")


if __name__ == "__main__":
    unittest.main()
