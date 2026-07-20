from __future__ import annotations

import os
import re
from pathlib import Path

from .storage import WorkflowError


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def load_env_file(path: Path) -> None:
    """Load a simple local .env file without expanding commands or variables."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise WorkflowError(f"Could not read environment file: {path}") from error
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise WorkflowError(
                f"Environment file line {line_number} must use NAME=VALUE"
            )
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if _ENV_NAME.fullmatch(name) is None:
            raise WorkflowError(
                f"Environment file line {line_number} has an invalid name"
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif value.startswith(("\"", "'")) or value.endswith(("\"", "'")):
            raise WorkflowError(
                f"Environment file line {line_number} has mismatched quotes"
            )
        if "\x00" in value or "\r" in value or "\n" in value:
            raise WorkflowError(
                f"Environment file line {line_number} has an invalid value"
            )
        os.environ[name] = value
