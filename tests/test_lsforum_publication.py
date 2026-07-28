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
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/process-weixin-submissions/scripts/process_weixin_submissions.py"
SCRIPTS = CLI.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from weixin_submission.lsforum_blog import LsforumPublicationAdapter
from weixin_submission.publication import PublicationError
from weixin_submission.schema_validation import SchemaValidationError


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
                parsed = urlparse(self.path)
                parts = parsed.path.rstrip("/").split("/")
                slug = parts[-1]
                owner.requests.append(
                    {
                        "method": "GET",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                    }
                )
                post = owner.posts.get(slug)
                if post is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if post.get("status") != "published" or post.get("deleted"):
                    self.send_response(404)
                    self.end_headers()
                    return
                self._json(
                    200,
                    {
                        "kind": "external",
                        "slug": slug,
                        "url": f"/posts/{slug}",
                        "title": post["title"],
                        "content": post["content"],
                        "image": post.get("image"),
                        "authorName": post["author"]["name"],
                    },
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
                self._json(
                    201,
                    {
                        "ok": True,
                        "slug": payload["slug"],
                        "url": owner.public_url(payload["slug"]),
                        "status": payload["status"],
                        "item": {
                            **owner.posts[payload["slug"]],
                            "kind": "external",
                            "slug": payload["slug"],
                        },
                        "version": 1,
                    },
                )


            def _request_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length == 0:
                    return {}
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise AssertionError("Expected a JSON object")
                return value

            def _json(self, status: int, value: object) -> None:
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
        host = self.server.server_address[0]
        port = self.server.server_address[1]
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
                {
                    "message_id": "h",
                    "kind": "text",
                    "text": (
                        "#投稿\n"
                        "author.name: Writer One\n"
                        "author.slug: writer-one\n"
                        "postType: opinion\n"
                        "category: Community"
                    ),
                },
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

    def test_http_adapter_uses_direct_publication_fields_and_persists_no_secret(self) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            result = self.run_auto()

        publication = result["publication_results"][0]
        self.assertEqual(publication["status"], "publication_confirmed")
        posts = [request for request in blog.requests if request["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["authorization"], "Bearer super-secret-test-key")
        self.assertEqual(posts[0]["payload"]["author"]["name"], "Writer One")
        self.assertEqual(posts[0]["payload"]["category"], "Community")
        self.assertEqual(posts[0]["payload"]["status"], "published")
        self.assertIn("content", posts[0]["payload"])
        lookups = [request for request in blog.requests if request["method"] == "GET"]
        self.assertEqual(len(lookups), 1)
        self.assertIsNone(lookups[0]["authorization"])
        self.assertFalse(lookups[0]["path"].endswith("?manage=true"))
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
        self.assertNotIn("etag", publication_record["external_result"])
        for path in self.repository.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"super-secret-test-key", path.read_bytes())

    def test_direct_fields_use_v07_name_based_author_identity(self) -> None:
        with LocalBlog() as blog:
            self.write_config(blog)
            self.append_submission()
            result = self.run_auto()
            publication_id = result["publication_results"][0]["publication_id"]
            request = json.loads(
                (
                    self.repository
                    / "publications"
                    / publication_id
                    / "request.json"
                ).read_text("utf-8")
            )
            recovered = LsforumPublicationAdapter(self.config).confirm(request)

        post = next(item for item in blog.requests if item["method"] == "POST")
        self.assertEqual(
            post["payload"]["author"],
            {
                "slug": "writer-one",
                "name": "Writer One",
            },
        )
        self.assertNotIn("authorName", post["payload"])
        self.assertNotIn("excerpt", post["payload"])
        self.assertNotIn("orgSlug", post["payload"])
        self.assertEqual(post["payload"]["postType"], "opinion")
        self.assertIsNotNone(recovered)

    def test_http_adapter_sends_and_recovers_the_selected_cover_image(self) -> None:
        cover_url = (
            "https://example.public.blob.vercel-storage.com/assets/cover.jpg"
        )
        with LocalBlog() as blog:
            self.write_config(blog)
            adapter = LsforumPublicationAdapter(self.config)
            request = {
                "slug": "post-with-cover",
                "title": "Post with cover",
                "body_markdown": f"Body\n\n![Cover]({cover_url})\n",
                "images": [cover_url],
                "cover_image": cover_url,
                "publication_fields": {
                    "author": {"name": "Writer One"},
                    "category": "Community",
                },
            }

            adapter.publish(request)
            recovered = adapter.confirm(request)

        post = next(item for item in blog.requests if item["method"] == "POST")
        self.assertEqual(post["payload"]["image"], cover_url)
        self.assertIn(cover_url, post["payload"]["content"])
        self.assertIsNotNone(recovered)

    def test_blog_config_rejects_local_target_mapping(self) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.test/api/v1",
                    "api_key_env": "LSFORUM_TEST_KEY",
                    "targets": {"writer-one": {"author": {"name": "Writer One"}}},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(SchemaValidationError) as raised:
            LsforumPublicationAdapter(self.config)
        self.assertIn("unknown fields ['targets']", str(raised.exception))

    def test_direct_fields_reject_deprecated_external_author_id(self) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.test/api/v1",
                    "api_key_env": "LSFORUM_TEST_KEY",
                }
            ),
            encoding="utf-8",
        )
        adapter = LsforumPublicationAdapter(self.config)

        with self.assertRaises(PublicationError) as raised:
            adapter.validate_request(
                {
                    "title": "Title",
                    "body_markdown": "Body",
                    "publication_fields": {
                        "author": {
                            "name": "Writer One",
                            "externalId": "ignored-writer-id",
                        }
                    },
                }
            )

        self.assertEqual(raised.exception.code, "publication_request_invalid")

    def test_direct_fields_reject_author_name_with_identity_whitespace(self) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.test/api/v1",
                    "api_key_env": "LSFORUM_TEST_KEY",
                }
            ),
            encoding="utf-8",
        )
        adapter = LsforumPublicationAdapter(self.config)

        with self.assertRaises(PublicationError) as raised:
            adapter.validate_request(
                {
                    "title": "Title",
                    "body_markdown": "Body",
                    "publication_fields": {
                        "author": {"name": "Writer One "}
                    },
                }
            )

        self.assertEqual(raised.exception.code, "publication_request_invalid")

    def test_v07_rejects_removed_author_and_organization_fields(self) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.test/api/v1",
                    "api_key_env": "LSFORUM_TEST_KEY",
                }
            ),
            encoding="utf-8",
        )
        adapter = LsforumPublicationAdapter(self.config)
        for field, value in (("author.title", "Editor"), ("author.orgSlug", "community"), ("orgSlug", "community"), ("orgName", "Community")):
            with self.subTest(field=field), self.assertRaises(PublicationError) as raised:
                publication_fields = {"author": {"name": "Writer One"}}
                target = publication_fields["author"] if field.startswith("author.") else publication_fields
                target[field.split(".")[-1]] = value
                adapter.validate_request({
                    "title": "Title",
                    "body_markdown": "Body",
                    "images": [],
                    "publication_fields": publication_fields,
                })
            self.assertEqual(raised.exception.code, "publication_request_invalid")

    def test_v07_post_response_requires_version_but_public_recovery_does_not(
        self,
    ) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "adapter": "lsforum",
                    "base_url": "https://example.test/api/v1",
                    "api_key_env": "LSFORUM_TEST_KEY",
                }
            ),
            encoding="utf-8",
        )
        adapter = LsforumPublicationAdapter(self.config)
        response = {
            "ok": True,
            "slug": "post",
            "url": "https://example.test/posts/post",
            "status": "published",
            "item": {"status": "published"},
        }

        with self.assertRaises(PublicationError) as raised:
            adapter.normalize_response(response)
        recovered = adapter.normalize_response({**response, "recovered": True})

        self.assertEqual(raised.exception.code, "blog_response_invalid")
        self.assertNotIn("version", recovered)

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
                        "text": "#投稿\nauthor.name: writer-one",
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

    def test_public_get_recovery_does_not_require_version_or_etag(self) -> None:
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
            resumed = self.run_auto()

        result = resumed["publication_results"][0]
        publication_path = self.repository / "publications" / result["publication_id"] / "publication.json"
        publication = json.loads(publication_path.read_text("utf-8"))
        self.assertNotIn("version", publication["external_result"])
        self.assertNotIn("etag", publication["external_result"])

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
