#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from weixin_submission.schema_validation import SchemaValidationError, milestones
from weixin_submission.rewrite import ScriptedRewriteOutcome
from weixin_submission.storage import WorkflowError, repository_status
from weixin_submission.writer_lock import acquire_writer_lock
from weixin_submission.workflow import (
    enable_retry,
    initialize_scripted_chat,
    run_scripted_chat,
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process manually triggered WeChat submissions."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    initialize = subparsers.add_parser("initialize", help="Initialize a task repository.")
    initialize.add_argument("--repository", type=Path, required=True)
    initialize.add_argument("--scripted-chat", type=Path, required=True)

    run = subparsers.add_parser("run", help="Run the next scripted chat window.")
    run.add_argument("--repository", type=Path, required=True)
    run.add_argument("--scripted-chat", type=Path, required=True)
    run.add_argument("--fake-blog-directory", type=Path, required=True)
    run.add_argument(
        "--scripted-rewrite-outcome",
        type=ScriptedRewriteOutcome,
        choices=tuple(ScriptedRewriteOutcome),
        default=ScriptedRewriteOutcome.SUCCESS,
        help="Validation-only scripted content-processing outcome.",
    )
    run.add_argument(
        "--simulate-interruption-after",
        choices=milestones(),
    )

    status = subparsers.add_parser("status", help="Read task repository status.")
    status.add_argument("--repository", type=Path, required=True)

    retry = subparsers.add_parser("retry", help="Re-enable a retry-exhausted task.")
    retry.add_argument("--repository", type=Path, required=True)
    retry.add_argument("--task-id", required=True)
    return parser


def execute(arguments: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if arguments.operation == "initialize":
        with acquire_writer_lock(arguments.repository, "initialize"):
            return 0, initialize_scripted_chat(
                arguments.repository, arguments.scripted_chat
            )
    if arguments.operation == "run":
        with acquire_writer_lock(arguments.repository, "run"):
            return 0, run_scripted_chat(
                arguments.repository,
                arguments.scripted_chat,
                arguments.fake_blog_directory,
                arguments.simulate_interruption_after,
                arguments.scripted_rewrite_outcome,
            )
    if arguments.operation == "status":
        return 0, repository_status(arguments.repository)
    if arguments.operation == "retry":
        with acquire_writer_lock(arguments.repository, "retry"):
            return 0, enable_retry(arguments.repository, arguments.task_id)
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
