from __future__ import annotations

import json
import os
import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .schema_validation import validate_record
from .storage import WorkflowError, new_id, read_json, utc_now


LOCK_FILENAME = "writer.lock"


@contextmanager
def acquire_writer_lock(repository: Path, operation: str) -> Iterator[None]:
    repository.mkdir(parents=True, exist_ok=True)
    lock_path = repository / LOCK_FILENAME
    owner_id = new_id("owner")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "owner_id": owner_id,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "operation": operation,
        "started_at": utc_now(),
    }
    validate_record("writer-lock", payload)
    try:
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        existing = read_writer_lock(repository)
        raise WorkflowError(
            f"Repository writer lock is already held: {existing}"
        ) from error
    try:
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)

    try:
        yield
    finally:
        current: dict[str, Any] | None
        try:
            current = read_json(lock_path)
        except WorkflowError:
            current = None
        if isinstance(current, dict) and current.get("owner_id") == owner_id:
            lock_path.unlink()


def read_writer_lock(repository: Path) -> dict[str, Any] | None:
    lock_path = repository / LOCK_FILENAME
    if not lock_path.exists():
        return None
    value = read_json(lock_path)
    validate_record("writer-lock", value)
    return value


def describe_writer_lock(repository: Path) -> dict[str, Any] | None:
    value = read_writer_lock(repository)
    if value is None:
        return None
    return {**value, "automatic_reclaim": False}
