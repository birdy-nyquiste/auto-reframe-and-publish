#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from weixin_submission.schema_validation import SchemaValidationError, milestones
from weixin_submission.rewrite import CodexCliGenerator, ScriptedRewriteOutcome
from weixin_submission.storage import WorkflowError, repository_status
from weixin_submission.writer_lock import acquire_writer_lock
from weixin_submission.workflow import (
    enable_retry,
    initialize_macos_computer_use,
    initialize_scripted_chat,
    publish_existing_task,
    run_macos_computer_use_window,
    run_scripted_chat,
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process manually triggered WeChat submissions."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    initialize = subparsers.add_parser(
        "initialize", help="Initialize a task repository."
    )
    initialize.add_argument("--repository", type=Path, required=True)
    initialize_source = initialize.add_mutually_exclusive_group(required=True)
    initialize_source.add_argument("--scripted-chat", type=Path)
    initialize_source.add_argument("--macos-marker-id")
    initialize.add_argument("--scripted-clipboard", type=Path)

    run = subparsers.add_parser("run", help="Run the next scripted chat window.")
    run.add_argument("--repository", type=Path, required=True)
    run_source = run.add_mutually_exclusive_group(required=True)
    run_source.add_argument("--scripted-chat", type=Path)
    run_source.add_argument("--macos-window", type=Path)
    run.add_argument("--scripted-clipboard", type=Path)
    run.add_argument(
        "--rewrite-generator",
        choices=("scripted", "codex"),
        help=(
            "Content generator; defaults to codex for macOS Computer Use and "
            "scripted for validation fixtures."
        ),
    )
    run.add_argument(
        "--codex-command",
        default="codex",
        help="Codex executable used only with --rewrite-generator codex.",
    )
    run.add_argument(
        "--publication",
        choices=("none", "auto"),
        default="none",
        help="Public publication is opt-in for this run; omission means none.",
    )
    blog = run.add_mutually_exclusive_group()
    blog.add_argument(
        "--fake-blog-directory",
        type=Path,
        help="Validation-only fake Blog service used when publication is auto.",
    )
    blog.add_argument(
        "--blog-config",
        type=Path,
        help="Non-secret LSForum adapter configuration used when publication is auto.",
    )
    run.add_argument(
        "--scripted-rewrite-outcome",
        type=ScriptedRewriteOutcome,
        choices=tuple(ScriptedRewriteOutcome),
        default=ScriptedRewriteOutcome.SUCCESS,
        help="Validation-only scripted content-processing outcome.",
    )
    run.add_argument(
        "--simulate-interruption-after",
        choices=(
            *milestones(),
            "publication_request_ready",
            "publication_send_started",
            "publication_response_received",
        ),
    )

    status = subparsers.add_parser("status", help="Read task repository status.")
    status.add_argument("--repository", type=Path, required=True)
    status.add_argument("--disk-warning-bytes", type=int)

    retry = subparsers.add_parser("retry", help="Re-enable a retry-exhausted task.")
    retry.add_argument("--repository", type=Path, required=True)
    retry.add_argument("--task-id", required=True)

    publish = subparsers.add_parser(
        "publish", help="Publish one existing validated rewrite artifact."
    )
    publish.add_argument("--repository", type=Path, required=True)
    publish.add_argument("--task-id", required=True)
    publish.add_argument(
        "--image-policy",
        choices=("preserve", "omit"),
        default="preserve",
        help=(
            "Preserve local-image requirements, or explicitly derive an audited "
            "text-only publication body."
        ),
    )
    publish_blog = publish.add_mutually_exclusive_group(required=True)
    publish_blog.add_argument("--fake-blog-directory", type=Path)
    publish_blog.add_argument("--blog-config", type=Path)
    return parser


def execute(arguments: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if arguments.operation == "initialize":
        with acquire_writer_lock(arguments.repository, "initialize"):
            if arguments.scripted_chat is not None:
                return 0, initialize_scripted_chat(
                    arguments.repository,
                    arguments.scripted_chat,
                    arguments.scripted_clipboard,
                )
            return 0, initialize_macos_computer_use(
                arguments.repository,
                arguments.macos_marker_id,
            )
    if arguments.operation == "run":
        generator_name = arguments.rewrite_generator or (
            "codex" if arguments.macos_window is not None else "scripted"
        )
        if (
            arguments.macos_window is not None
            and generator_name == "scripted"
            and arguments.publication == "auto"
        ):
            raise WorkflowError(
                "macOS scripted rewrite artifacts cannot be automatically published"
            )
        rewrite_generator = (
            CodexCliGenerator(arguments.codex_command)
            if generator_name == "codex"
            else None
        )
        with acquire_writer_lock(arguments.repository, "run"):
            if arguments.scripted_chat is not None:
                return 0, run_scripted_chat(
                    arguments.repository,
                    arguments.scripted_chat,
                    arguments.publication,
                    arguments.fake_blog_directory,
                    arguments.blog_config,
                    arguments.simulate_interruption_after,
                    arguments.scripted_rewrite_outcome,
                    arguments.scripted_clipboard,
                    rewrite_generator,
                )
            return 0, run_macos_computer_use_window(
                arguments.repository,
                arguments.macos_window,
                arguments.publication,
                arguments.fake_blog_directory,
                arguments.blog_config,
                arguments.simulate_interruption_after,
                arguments.scripted_rewrite_outcome,
                rewrite_generator,
            )
    if arguments.operation == "status":
        return 0, repository_status(arguments.repository, arguments.disk_warning_bytes)
    if arguments.operation == "retry":
        with acquire_writer_lock(arguments.repository, "retry"):
            return 0, enable_retry(arguments.repository, arguments.task_id)
    if arguments.operation == "publish":
        with acquire_writer_lock(arguments.repository, "publish"):
            return 0, publish_existing_task(
                arguments.repository,
                arguments.task_id,
                image_policy=arguments.image_policy,
                fake_blog_directory=arguments.fake_blog_directory,
                blog_config=arguments.blog_config,
            )
    raise WorkflowError(f"Unsupported operation: {arguments.operation}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    try:
        exit_code, result = execute(arguments)
    except (WorkflowError, SchemaValidationError) as error:
        print(
            json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
