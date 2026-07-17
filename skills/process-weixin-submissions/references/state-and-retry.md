# Durable state and retry

The current durable repository version is 3. It contains peer `runs/`, `tasks/`, and `publications/` aggregates.

Content-task milestones are:

1. `task_created`
2. `raw_evidence_ready`
3. `structured_source_ready`
4. `rewrite_artifact_ready`

Publication is not a fifth content milestone. A publication has its own `publication_created`, `request_ready`, and `publication_confirmed` milestones plus an independent blocker. A content task remains complete even when publication is blocked or fails.

Active work is represented by append-only attempt events, not a persisted running task milestone. State-changing content events carry `state_after`; `task.json` is the rebuildable projection. Blockers are independent from progress.

## Recovery

A normal `run` journals the complete input window, fixed run/task IDs, and publication selection in `repository.json.pending_window` before advancing the marker cursor. Re-entry must use the original selection; it cannot widen an interrupted `none` run to `auto` or downgrade an already authorized `auto` run while the window is pending.

The run reconciles content projections and resumes executable content tasks after their last committed milestone. It does not reprocess a task already at `rewrite_artifact_ready`. A previous run left in `processing` is marked `interrupted` and linked to the recovering run.

Rewrite generation or validation failures stay at `structured_source_ready` with immutable attempt evidence. The commit anchor and all transitive hashes are checked before `rewrite_artifact_ready` is committed and again when an authorized publication is derived.

Publication requests are immutable. Explicit failures and `outcome_unknown` are publication blockers, never content blockers. Because LSForum has no idempotency key, `outcome_unknown` is not eligible for an automatic POST retry.

`--simulate-interruption-after <content-milestone>` is a validation-only scripted option.

## Retry

A normal run executes content tasks with `retry_pending`, skips `retry_exhausted`, and skips `permanent_failure`. Use:

```text
python scripts/process_weixin_submissions.py retry \
  --repository <task-repository> \
  --task-id <retry-exhausted-task-id>
```

This creates an auditable retry run, increments the task retry generation, and restores `retry_pending`. It does not publish. Publication unknown-outcome resolution requires a future explicit workflow and must not be forced through content retry.

## Writer lock and status

Every mutating operation uses `<task-repository>/writer.lock`. Never delete or replace a lock merely because its process looks old. `status` is read-only and reports content milestones, publication milestones/blockers, run states, the lock, and repository byte usage.
