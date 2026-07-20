# Durable state and retry

The current durable repository version is 3. It contains peer `runs/`, `tasks/`, and `publications/` aggregates.

Content-task milestones are:

1. `task_created`
2. `raw_evidence_ready`
3. `structured_source_ready`
4. `rewrite_artifact_ready`

Publication is not a fifth content milestone. A publication has its own `publication_created`, `request_ready`, and `publication_confirmed` milestones plus an independent blocker. A content task remains complete even when publication is blocked or fails.

`publish` creates its own run and a new publication aggregate for one existing `rewrite_artifact_ready` task. This keeps later operator-authorized presentation choices, such as an audited text-only version, separate from the immutable content task and from earlier blocked publication attempts.

Active work is represented by append-only attempt events, not a persisted running task milestone. State-changing content events carry `state_after`; `task.json` is the rebuildable projection. Blockers are independent from progress.

## Recovery

A normal `run` journals the complete input window, fixed run/task IDs, and publication selection in `repository.json.pending_window` before advancing the marker cursor. Re-entry must use the original selection; it cannot widen an interrupted `none` run to `auto` or downgrade an already authorized `auto` run while the window is pending.

The run reconciles content projections and resumes executable content tasks after their last committed milestone. It does not reprocess a task already at `rewrite_artifact_ready`. A previous run left in `processing` is marked `interrupted` and linked to the recovering run.

Rewrite generation or validation failures stay at `structured_source_ready` with immutable attempt evidence. The commit anchor and all transitive hashes are checked before `rewrite_artifact_ready` is committed and again when an authorized publication is derived.

Publication requests are immutable. Explicit failures and `outcome_unknown` are publication blockers, never content blockers. Because LSForum has no idempotency key, `outcome_unknown` is not eligible for an automatic POST retry.

An explicitly authorized `auto` run also reconciles unfinished publication aggregates using their original fixed request. A `request_ready` publication with a fixed adapter destination, durable `prepared` evidence, and no `send_started` evidence may continue with one POST. If `send_started` exists, recovery performs confirmation GET only. An exact public match commits `publication_confirmed`; absence, conflict, or an inconclusive lookup commits `outcome_unknown`. Legacy requests without a fixed destination are blocked without network access. A `none` run never resumes publication work.

`--simulate-interruption-after <milestone>` is validation-only. In addition to content milestones, `publication_request_ready` simulates a definitely pre-send interruption, `publication_send_started` simulates an interruption after the external call may have begun, and `publication_response_received` simulates a successful POST whose response has not yet been committed locally.

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
