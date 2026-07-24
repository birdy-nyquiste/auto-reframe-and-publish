from __future__ import annotations


RETRY_BUDGETS = {
    "capture_raw_evidence": {
        "capture_incomplete": 2,
    },
    "generate_rewrite": {
        "rewrite_generation": 2,
    },
}

RECOVERABLE_LEGACY_PERMANENT_FAILURES = frozenset(
    {
        ("generate_rewrite", "rewrite_generation", "codex_generation_failed"),
        ("generate_rewrite", "rewrite_generation", "codex_generation_timed_out"),
    }
)


def retry_budget(operation: str, error_category: str) -> int | None:
    return RETRY_BUDGETS.get(operation, {}).get(error_category)


def recoverable_permanent_failure_budget(blocker: object) -> int | None:
    if not isinstance(blocker, dict) or blocker.get("kind") != "permanent_failure":
        return None
    identity = (
        blocker.get("operation"),
        blocker.get("error_category"),
        blocker.get("error_code"),
    )
    if identity not in RECOVERABLE_LEGACY_PERMANENT_FAILURES:
        return None
    return retry_budget(str(identity[0]), str(identity[1]))
