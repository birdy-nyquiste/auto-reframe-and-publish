from __future__ import annotations


SCRIPTED_RETRY_BUDGETS = {
    "capture_raw_evidence": {
        "capture_incomplete": 2,
    }
}


def retry_budget(operation: str, error_category: str) -> int | None:
    return SCRIPTED_RETRY_BUDGETS.get(operation, {}).get(error_category)
