from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import write_json


class FakeBlogAdapter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def create_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        drafts = self.directory / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        existing = sorted(drafts.glob("draft-*.json"))
        draft_id = f"draft-{len(existing) + 1:06d}"
        response = {
            "draft_id": draft_id,
            "status": "accepted",
            "preview_url": f"https://blog.example.test/drafts/{draft_id}",
            "adapter": "fake",
        }
        write_json(drafts / f"{draft_id}.json", {"request": request, "response": response})
        return response

