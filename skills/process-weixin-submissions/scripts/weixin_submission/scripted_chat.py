from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .scripted_clipboard import ScriptedClipboard
from .storage import WorkflowError, new_id, read_json, utc_now, write_json


@dataclass(frozen=True)
class InputWindow:
    conversation: str
    previous_marker_id: str
    current_marker_id: str
    messages: tuple[dict[str, Any], ...]


def _read_chat(path: Path) -> dict[str, Any]:
    chat = read_json(path)
    if chat.get("schema_version") != 1:
        raise WorkflowError("scripted chat schema_version must be 1")
    if chat.get("conversation") != "file-transfer-assistant":
        raise WorkflowError("scripted chat must represent file-transfer-assistant")
    messages = chat.get("messages")
    delayed = chat.get("arrive_after_next_marker", [])
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise WorkflowError("scripted chat messages must be a list of objects")
    if not isinstance(delayed, list) or not all(isinstance(item, dict) for item in delayed):
        raise WorkflowError("arrive_after_next_marker must be a list of objects")
    return chat


def _send_marker(
    path: Path, clipboard: ScriptedClipboard
) -> tuple[str, dict[str, Any]]:
    chat = _read_chat(path)
    marker_id = new_id("marker")
    marker_text = f"#批次 {marker_id}"
    clipboard.paste_text(marker_text)
    pasted_text = clipboard.read_for_paste()
    if pasted_text != marker_text:
        raise WorkflowError("Scripted clipboard changed the batch marker text")
    marker = {
        "message_id": marker_id,
        "kind": "batch_marker",
        "marker_id": marker_id,
        "text": pasted_text,
        "sent_at": utc_now(),
    }
    chat["messages"].append(marker)
    chat["messages"].extend(chat.get("arrive_after_next_marker", []))
    chat["arrive_after_next_marker"] = []
    write_json(path, chat)
    clipboard.clear()
    return marker_id, chat


def establish_baseline(
    path: Path, clipboard: ScriptedClipboard
) -> tuple[str, str]:
    marker_id, chat = _send_marker(path, clipboard)
    return marker_id, str(chat["conversation"])


def capture_next_window(
    path: Path, previous_marker_id: str, clipboard: ScriptedClipboard
) -> InputWindow:
    existing_chat = _read_chat(path)
    existing_messages = existing_chat["messages"]
    previous_positions = [
        index
        for index, message in enumerate(existing_messages)
        if message.get("kind") == "batch_marker"
        and message.get("marker_id") == previous_marker_id
    ]
    if not previous_positions:
        raise WorkflowError("The repository baseline marker is missing from scripted chat")
    previous_index = previous_positions[-1]
    orphaned_markers = [
        (index, str(message.get("marker_id")))
        for index, message in enumerate(
            existing_messages[previous_index + 1 :], start=previous_index + 1
        )
        if message.get("kind") == "batch_marker"
        and isinstance(message.get("marker_id"), str)
    ]
    if orphaned_markers:
        current_index, current_marker_id = orphaned_markers[0]
        return InputWindow(
            conversation=str(existing_chat["conversation"]),
            previous_marker_id=previous_marker_id,
            current_marker_id=current_marker_id,
            messages=tuple(existing_messages[previous_index + 1 : current_index]),
        )

    current_marker_id, chat = _send_marker(path, clipboard)
    messages = chat["messages"]
    marker_positions = {
        message.get("marker_id"): index
        for index, message in enumerate(messages)
        if message.get("kind") == "batch_marker"
    }
    try:
        previous_index = marker_positions[previous_marker_id]
        current_index = marker_positions[current_marker_id]
    except KeyError as error:
        raise WorkflowError(
            "The repository baseline marker is missing from scripted chat"
        ) from error
    if previous_index >= current_index:
        raise WorkflowError("Scripted chat markers are out of order")
    window_messages = messages[previous_index + 1 : current_index]
    return InputWindow(
        conversation=str(chat["conversation"]),
        previous_marker_id=previous_marker_id,
        current_marker_id=current_marker_id,
        messages=tuple(window_messages),
    )
