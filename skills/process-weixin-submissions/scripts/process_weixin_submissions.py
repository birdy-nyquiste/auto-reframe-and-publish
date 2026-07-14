#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from weixin_submission.storage import WorkflowError, repository_status
from weixin_submission.workflow import (
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

    status = subparsers.add_parser("status", help="Read task repository status.")
    status.add_argument("--repository", type=Path, required=True)

    retry = subparsers.add_parser(
        "retry", help="Retry a task after durable retry support is implemented."
    )
    retry.add_argument("--repository", type=Path, required=True)
    retry.add_argument("--task-id", required=True)
    return parser


def execute(arguments: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if arguments.operation == "initialize":
        return 0, initialize_scripted_chat(
            arguments.repository, arguments.scripted_chat
        )
    if arguments.operation == "run":
        return 0, run_scripted_chat(
            arguments.repository,
            arguments.scripted_chat,
            arguments.fake_blog_directory,
        )
    if arguments.operation == "status":
        return 0, repository_status(arguments.repository)
    if arguments.operation == "retry":
        return 3, {
            "status": "not_available",
            "operation": "retry",
            "task_id": arguments.task_id,
            "reason": "Durable retry is implemented by Ticket 03.",
        }
    raise WorkflowError(f"Unsupported operation: {arguments.operation}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    try:
        exit_code, result = execute(arguments)
    except WorkflowError as error:
        print(
            json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
