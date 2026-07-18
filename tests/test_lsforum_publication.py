from __future__ import annotations

import hashlib
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
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/process-weixin-submissions/scripts/process_weixin_submissions.py"
SCRIPTS = CLI.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from weixin_submission.lsforum_blog import LsforumPublicationAdapter
from weixin_submission.publication import PublicationError


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
        self.revisions: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                parts = parsed.path.rstrip("/").split("/")
                slug = parts[-2] if parts[-1] == "revisions" else parts[-1]
                owner.requests.append(
                    {
                        "method": "GET",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                    }
                )
                if parts[-1] == "revisions":
                    self._json(200, owner.revisions.get(slug, []))
                    return
                post = owner.posts.get(slug)
                if post is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                manage = parse_qs(parsed.query).get("manage") == ["true"]
                if (post.get("status") != "published" or post.get("deleted")) and not manage:
                    self.send_response(404)
                    self.end_headers()
                    return
                self._json(
                    200,
                    {**post, "slug": slug, "url": owner.public_url(slug)},
                    etag=(
                        None
                        if owner.mode == "manage_without_etag"
                        else f'"{post["version"]}"'
                    ),
                )

            def do_POST(self) -> None:
                payload = self._request_body()
                owner.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "payload": payload,
                    }
                )
                if self.path.endswith("/restore"):
                    slug = self.path.rstrip("/").split("/")[-2]
                    post = owner.posts.get(slug)
                    if post is None:
                        self._json(404, {"message": "Post not found"})
                        return
                    post["deleted"] = False
                    post["version"] += 1
                    owner.revisions.setdefault(slug, []).append(
                        {"operation": "restore", "version": post["version"]}
                    )
                    self._json(200, post, etag=f'"{post["version"]}"')
                    return
                if owner.mode == "reject":
                    self._json(400, {"message": "Payload was rejected"})
                    return
                if owner.mode == "conflict_disconnect":
                    owner.posts[payload["slug"]] = {
                        **payload,
                        "content": "Different content under the same slug",
                        "version": 1,
                        "deleted": False,
                    }
                if owner.mode == "disconnect":
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                if owner.mode == "conflict_disconnect":
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                owner.posts[payload["slug"]] = {
                    **payload,
                    "status": payload.get("status", "published"),
                    "version": 1,
                    "deleted": False,
                }
                owner.revisions[payload["slug"]] = [
                    {"operation": "create", "version": 1}
                ]
                self._json(
                    201,
                    {
                        "ok": True,
                        "slug": payload["slug"],
                        "url": owner.public_url(payload["slug"]),
                        "item": {"kind": "external", "slug": payload["slug"]},
                        "version": 1,
                    },
                    etag='"1"',
                )

            def do_PATCH(self) -> None:
                slug = urlparse(self.path).path.rstrip("/").split("/")[-1]
                payload = self._request_body()
                owner.requests.append(
                    {
                        "method": "PATCH",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "if_match": self.headers.get("If-Match"),
                        "payload": payload,
                    }
                )
                post = owner.posts.get(slug)
                if post is None:
                    self._json(404, {"message": "Post not found"})
                    return
                if self.headers.get("If-Match") != f'"{post["version"]}"':
                    self._json(412, {"message": "Version is stale"})
                    return
                post.update(payload)
                post["version"] += 1
                owner.revisions.setdefault(slug, []).append(
                    {"operation": "update", "version": post["version"]}
                )
                self._json(200, post, etag=f'"{post["version"]}"')

            def do_DELETE(self) -> None:
                slug = urlparse(self.path).path.rstrip("/").split("/")[-1]
                owner.requests.append(
                    {
                        "method": "DELETE",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                    }
                )
                post = owner.posts.get(slug)
                if post is None:
                    self._json(404, {"message": "Post not found"})
                    return
                post["deleted"] = True
                post["version"] += 1
                owner.revisions.setdefault(slug, []).append(
                    {"operation": "delete", "version": post["version"]}
                )
                self._json(200, post, etag=f'"{post["version"]}"')

            def _request_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length == 0:
                    return {}
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise AssertionError("Expected a JSON object")
                return value

            def _json(self, status: int, value: object, etag: str | None = None) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if etag is not None:
                    self.send_header("ETag", etag)
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

    def run_auto(self, *extra: object) -> dict[str, Any]:
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
            *extra,
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
        self.assertEqual(posts[0]["payload"]["status"], "published")
        self.assertIn("content", posts[0]["payload"])
        lookups = [request for request in blog.requests if request["method"] == "GET"]
        self.assertEqual(len(lookups), 1)
        self.assertEqual(lookups[0]["authorization"], "Bearer super-secret-test-key")
        self.assertTrue(lookups[0]["path"].endswith("?manage=true"))
        publication_record = json.loads(
            (
                self.repository
                / "publications"
                / publication["publication_id"]
                / "publication.json"
            ).read_text("utf-8")
        )
        self.assertEqual(publication_record["external_result"]["content_status"], "published")
        self.assertEqual(publication_record["external_result"]["version"], 1)
        self.assertEqual(publication_record["external_result"]["etag"], '"1"')
        for path in self.repository.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"super-secret-test-key", path.read_bytes())

    def test_versioned_management_requests_use_auth_and_if_match(self) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            adapter = LsforumPublicationAdapter(self.config)
            blog.posts["managed-post"] = {
                "slug": "managed-post",
                "title": "Original",
                "content": "Body",
                "authorName": "Writer One",
                "status": "draft",
                "version": 3,
                "deleted": False,
            }
            blog.revisions["managed-post"] = [
                {"operation": "create", "version": 1}
            ]

            managed = adapter.get_managed_post("managed-post")
            updated = adapter.patch_post(
                "managed-post", {"title": "Updated"}, version=3
            )
            with self.assertRaises(PublicationError) as stale:
                adapter.patch_post("managed-post", {"title": "Stale"}, version=3)
            deleted = adapter.soft_delete_post("managed-post")
            restored = adapter.restore_post("managed-post")
            revisions = adapter.list_revisions("managed-post")

        self.assertEqual(managed["body"]["status"], "draft")
        self.assertEqual(managed["body"]["version"], 3)
        self.assertEqual(updated["headers"]["etag"], '"4"')
        self.assertEqual(stale.exception.code, "blog_version_conflict")
        self.assertTrue(deleted["body"]["deleted"])
        self.assertFalse(restored["body"]["deleted"])
        self.assertEqual(len(revisions["body"]), 4)

        for request in blog.requests:
            self.assertEqual(
                request["authorization"], "Bearer super-secret-test-key"
            )
        patches = [request for request in blog.requests if request["method"] == "PATCH"]
        self.assertEqual([request["if_match"] for request in patches], ['"3"', '"3"'])
        self.assertTrue(blog.requests[0]["path"].endswith("?manage=true"))
        self.assertTrue(blog.requests[-1]["path"].endswith("/revisions"))

    def test_management_validation_blocks_unsafe_patch_without_http(self) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            adapter = LsforumPublicationAdapter(self.config)
            with self.assertRaises(PublicationError) as unsupported:
                adapter.patch_post("managed-post", {"slug": "replacement"}, version=1)
            with self.assertRaises(PublicationError) as invalid_version:
                adapter.patch_post("managed-post", {"title": "Updated"}, version='1"')

        self.assertEqual(unsupported.exception.code, "publication_request_invalid")
        self.assertEqual(invalid_version.exception.code, "publication_request_invalid")
        self.assertEqual(blog.requests, [])

    def test_confirmation_without_required_key_remains_configuration_blocked(
        self,
    ) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            adapter = LsforumPublicationAdapter(self.config)
            os.environ.pop("LSFORUM_TEST_KEY")
            with self.assertRaises(PublicationError) as missing_key:
                adapter.confirm({"slug": "managed-post"})

        self.assertEqual(missing_key.exception.blocker_kind.value, "needs_configuration")
        self.assertEqual(missing_key.exception.code, "api_key_missing")
        self.assertEqual(blog.requests, [])

    def test_confirmation_requires_explicit_undeleted_state(self) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            adapter = LsforumPublicationAdapter(self.config)
            blog.posts["managed-post"] = {
                "slug": "managed-post",
                "title": "Original",
                "content": "Body",
                "authorName": "Writer One",
                "status": "published",
                "version": 1,
            }
            request = {
                "slug": "managed-post",
                "title": "Original",
                "body_markdown": "Body",
                "target": {"mapped_fields": {"authorName": "Writer One"}},
            }
            with self.assertRaises(PublicationError) as ambiguous:
                adapter.confirm(request)

        self.assertEqual(ambiguous.exception.code, "publication_outcome_unknown")

    def test_non_ascii_api_key_blocks_before_http_and_persists_no_secret(
        self,
    ) -> None:
        invalid_key = "“super-secret-test-key”"
        os.environ["LSFORUM_TEST_KEY"] = invalid_key

        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            result = self.run_auto()

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "needs_configuration")
        self.assertEqual(publication["blocker_reason"], "api_key_invalid_format")
        self.assertEqual(blog.requests, [])
        for path in self.repository.rglob("*"):
            if path.is_file():
                self.assertNotIn(invalid_key.encode("utf-8"), path.read_bytes())

    def test_interrupted_request_ready_publication_resumes_once_with_same_slug(
        self,
    ) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            interrupted = run_cli(
                "run",
                "--repository",
                self.repository,
                "--scripted-chat",
                self.chat,
                "--publication",
                "auto",
                "--blog-config",
                self.config,
                "--simulate-interruption-after",
                "publication_request_ready",
            )
            self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
            self.assertEqual(blog.requests, [])

            publication_directories = list(
                (self.repository / "publications").iterdir()
            )
            self.assertEqual(len(publication_directories), 1)
            publication_id = publication_directories[0].name
            before = json.loads(
                (publication_directories[0] / "publication.json").read_text("utf-8")
            )
            self.assertEqual(before["milestone"], "request_ready")
            fixed_slug = before["slug"]
            origin_run_id = before["created_in_run"]

            resumed = self.run_auto()

        self.assertEqual(len(resumed["publication_results"]), 1)
        recovered = resumed["publication_results"][0]
        self.assertEqual(recovered["publication_id"], publication_id)
        self.assertEqual(recovered["status"], "publication_confirmed")
        after = json.loads(
            (publication_directories[0] / "publication.json").read_text("utf-8")
        )
        self.assertEqual(after["slug"], fixed_slug)
        self.assertEqual(after["milestone"], "publication_confirmed")
        self.assertEqual(
            len([request for request in blog.requests if request["method"] == "POST"]),
            1,
        )
        resumed_run = json.loads(
            (
                self.repository / "runs" / resumed["run_id"] / "run.json"
            ).read_text("utf-8")
        )
        self.assertEqual(resumed_run["created_publication_ids"], [])
        self.assertEqual(resumed_run["attempted_publication_ids"], [publication_id])
        origin_run = json.loads(
            (self.repository / "runs" / origin_run_id / "run.json").read_text(
                "utf-8"
            )
        )
        self.assertEqual(origin_run["created_publication_ids"], [publication_id])
        self.assertEqual(origin_run["attempted_publication_ids"], [])
        self.assertEqual(origin_run["recovered_by_run"], resumed["run_id"])
        origin_report = (
            self.repository / "runs" / origin_run_id / "report.md"
        ).read_text("utf-8")
        self.assertIn(publication_id, origin_report)

    def test_interrupted_send_started_publication_is_confirmed_without_repost(
        self,
    ) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            interrupted = run_cli(
                "run",
                "--repository",
                self.repository,
                "--scripted-chat",
                self.chat,
                "--publication",
                "auto",
                "--blog-config",
                self.config,
                "--simulate-interruption-after",
                "publication_send_started",
            )
            self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
            self.assertEqual(blog.requests, [])

            resumed = self.run_auto()
            repeated = self.run_auto()

        self.assertEqual(len(resumed["publication_results"]), 1)
        publication = resumed["publication_results"][0]
        self.assertEqual(publication["status"], "outcome_unknown")
        self.assertEqual(
            publication["blocker_reason"], "publication_outcome_unknown"
        )
        self.assertEqual(repeated["publication_results"], [])
        self.assertEqual(
            len([request for request in blog.requests if request["method"] == "POST"]),
            0,
        )
        self.assertEqual(
            len([request for request in blog.requests if request["method"] == "GET"]),
            1,
        )

    def test_corrupted_fixed_request_is_isolated_from_a_new_publication(
        self,
    ) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            interrupted = run_cli(
                "run",
                "--repository",
                self.repository,
                "--scripted-chat",
                self.chat,
                "--publication",
                "auto",
                "--blog-config",
                self.config,
                "--simulate-interruption-after",
                "publication_request_ready",
            )
            self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
            old_publication_directory = next(
                (self.repository / "publications").iterdir()
            )
            old_publication_id = old_publication_directory.name
            corrupted_request = json.loads(
                (old_publication_directory / "request.json").read_text("utf-8")
            )
            corrupted_request["body_markdown"] = "# Corrupted content"
            (old_publication_directory / "request.json").write_text(
                json.dumps(corrupted_request), encoding="utf-8"
            )

            chat = cast(dict[str, Any], json.loads(self.chat.read_text("utf-8")))
            chat["messages"].extend(
                [
                    {
                        "message_id": "h-new",
                        "kind": "text",
                        "text": "#投稿\n目标: writer-one",
                    },
                    {
                        "message_id": "a-new",
                        "kind": "official_account_article",
                        "title": "A new title",
                        "body": "A new copied source body.",
                        "source_url": "https://example.com/new-source",
                        "images": [],
                    },
                ]
            )
            self.chat.write_text(json.dumps(chat), encoding="utf-8")

            resumed = self.run_auto()

        results = {
            result["publication_id"]: result
            for result in resumed["publication_results"]
        }
        self.assertEqual(
            results[old_publication_id]["status"], "permanent_failure"
        )
        self.assertEqual(
            results[old_publication_id]["blocker_reason"],
            "publication_integrity_failed",
        )
        confirmed = [
            result
            for publication_id, result in results.items()
            if publication_id != old_publication_id
        ]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["status"], "publication_confirmed")
        self.assertEqual(
            len([request for request in blog.requests if request["method"] == "POST"]),
            1,
        )

    def test_accepted_post_is_confirmed_after_response_persistence_interruption(
        self,
    ) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            interrupted = run_cli(
                "run",
                "--repository",
                self.repository,
                "--scripted-chat",
                self.chat,
                "--publication",
                "auto",
                "--blog-config",
                self.config,
                "--simulate-interruption-after",
                "publication_response_received",
            )
            self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
            self.assertEqual(
                len(
                    [
                        request
                        for request in blog.requests
                        if request["method"] == "POST"
                    ]
                ),
                1,
            )
            publication_directory = next(
                (self.repository / "publications").iterdir()
            )
            publication_id = publication_directory.name
            before = json.loads(
                (publication_directory / "publication.json").read_text("utf-8")
            )
            self.assertEqual(before["milestone"], "request_ready")
            self.assertFalse((publication_directory / "response.json").exists())

            resumed = self.run_auto()

        self.assertEqual(len(resumed["publication_results"]), 1)
        recovered = resumed["publication_results"][0]
        self.assertEqual(recovered["publication_id"], publication_id)
        self.assertEqual(recovered["status"], "publication_confirmed")
        self.assertEqual(
            len([request for request in blog.requests if request["method"] == "POST"]),
            1,
        )

    def test_recovery_derives_concurrency_etag_when_manage_get_omits_header(
        self,
    ) -> None:
        with LocalBlog(mode="manage_without_etag") as blog:
            self.write_config(blog)
            self.append_submission()
            interrupted = run_cli(
                "run",
                "--repository",
                self.repository,
                "--scripted-chat",
                self.chat,
                "--publication",
                "auto",
                "--blog-config",
                self.config,
                "--simulate-interruption-after",
                "publication_response_received",
            )
            self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
            resumed = self.run_auto()

        result = resumed["publication_results"][0]
        publication = json.loads(
            (
                self.repository
                / "publications"
                / result["publication_id"]
                / "publication.json"
            ).read_text("utf-8")
        )
        self.assertEqual(publication["external_result"]["version"], 1)
        self.assertEqual(publication["external_result"]["etag"], '"1"')

    def test_legacy_request_without_fixed_destination_makes_no_http_request(
        self,
    ) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            interrupted = run_cli(
                "run",
                "--repository",
                self.repository,
                "--scripted-chat",
                self.chat,
                "--publication",
                "auto",
                "--blog-config",
                self.config,
                "--simulate-interruption-after",
                "publication_request_ready",
            )
            self.assertEqual(interrupted.returncode, 2, interrupted.stderr)
            publication_directory = next(
                (self.repository / "publications").iterdir()
            )
            publication = json.loads(
                (publication_directory / "publication.json").read_text("utf-8")
            )
            request = json.loads(
                (publication_directory / "request.json").read_text("utf-8")
            )
            request["contract_version"] = 1
            request.pop("destination")
            request_bytes = (
                json.dumps(request, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            (publication_directory / "request.json").write_bytes(request_bytes)
            attempt_directory = (
                publication_directory / "attempts" / publication["created_in_run"]
            )
            (attempt_directory / "request.json").write_bytes(request_bytes)
            prepared = json.loads(
                (attempt_directory / "prepared.json").read_text("utf-8")
            )
            prepared["request_sha256"] = hashlib.sha256(request_bytes).hexdigest()
            (attempt_directory / "prepared.json").write_text(
                json.dumps(prepared, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            resumed = self.run_auto()

        self.assertEqual(len(resumed["publication_results"]), 1)
        result = resumed["publication_results"][0]
        self.assertEqual(result["status"], "permanent_failure")
        self.assertEqual(result["blocker_reason"], "publication_integrity_failed")
        self.assertEqual(blog.requests, [])

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
