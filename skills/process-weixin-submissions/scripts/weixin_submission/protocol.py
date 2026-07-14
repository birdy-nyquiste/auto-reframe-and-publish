from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .storage import WorkflowError
from .submission import Submission, TaskHeaderError, parse_submission_messages


@dataclass(frozen=True)
class IntakeCandidate:
    raw_messages: tuple[dict[str, Any], ...]
    submission: Submission | None
    target_id: str | None
    blocker_reason: str | None
    blocker_message: str | None


def valid_candidate(
    submission: Submission, raw_messages: tuple[dict[str, Any], ...]
) -> IntakeCandidate:
    return IntakeCandidate(raw_messages, submission, submission.target_id, None, None)


def blocked_candidate(
    raw_messages: tuple[dict[str, Any], ...],
    reason: str,
    message: str,
    target_id: str | None = None,
) -> IntakeCandidate:
    return IntakeCandidate(raw_messages, None, target_id, reason, message)


def parse_input_window(
    messages: tuple[dict[str, Any], ...], window_id: str
) -> list[IntakeCandidate]:
    candidates: list[IntakeCandidate] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if _is_task_header(message):
            if index + 1 >= len(messages):
                candidates.append(
                    blocked_candidate(
                        (message,),
                        "missing_adjacent_article",
                        "Task header is not followed by an article card",
                    )
                )
                index += 1
                continue
            next_message = messages[index + 1]
            if _is_task_header(next_message):
                candidates.append(
                    blocked_candidate(
                        (message,),
                        "missing_adjacent_article",
                        "Task header is followed by another task header",
                    )
                )
                index += 1
                continue
            raw_messages = (message, next_message)
            if next_message.get("kind") != "official_account_article":
                candidates.append(
                    blocked_candidate(
                        raw_messages,
                        "unsupported_source_type",
                        f"Unsupported adjacent source kind: {next_message.get('kind')}",
                    )
                )
                index += 2
                continue
            try:
                submission = parse_submission_messages(list(raw_messages), window_id)
            except TaskHeaderError as error:
                candidates.append(
                    blocked_candidate(
                        raw_messages, error.reason, str(error), error.target_id
                    )
                )
            except WorkflowError as error:
                candidates.append(
                    blocked_candidate(
                        raw_messages, "invalid_source_content", str(error)
                    )
                )
            else:
                candidates.append(valid_candidate(submission, raw_messages))
            index += 2
            continue

        if message.get("kind") == "official_account_article":
            reason = "missing_task_header"
            detail = "Article card is not preceded by a task header"
        else:
            reason = "unsupported_source_type"
            detail = f"Unsupported standalone message kind: {message.get('kind')}"
        candidates.append(blocked_candidate((message,), reason, detail))
        index += 1
    return candidates


def _is_task_header(message: dict[str, Any]) -> bool:
    text = message.get("text")
    return (
        message.get("kind") in ("text", "task_header")
        and isinstance(text, str)
        and bool(text.splitlines())
        and text.splitlines()[0].strip() == "#投稿"
    )
