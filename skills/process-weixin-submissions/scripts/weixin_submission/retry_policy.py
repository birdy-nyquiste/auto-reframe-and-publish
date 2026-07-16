from __future__ import annotations


SCRIPTED_RETRY_BUDGETS = {
    "deliver_draft": {
        "transient": 2,
    }
}


def retry_budget(operation: str, error_category: str) -> int | None:
    return SCRIPTED_RETRY_BUDGETS.get(operation, {}).get(error_category)
