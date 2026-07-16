# Durable state and retry

The durable repository and task/event/run records described here are version 2. Version 1 was the pre-durability tracer format and is not interpreted as the same layout.

The task snapshot records only the latest committed milestone. The ordered milestones are:

1. `task_created`
2. `raw_evidence_ready`
3. `structured_source_ready`
4. `rewrite_artifact_ready`
5. `draft_delivery_confirmed`

Active work is never a task milestone. Each attempt is an append-only event linked to the run that performed it. State-changing events contain the validated `state_after` and are the atomic write-ahead record; `task.json` is its rebuildable current-state projection. A task blocker is either absent or one of `needs_input`, `retry_pending`, `retry_exhausted`, and `permanent_failure`. The bundled Schemas reject unknown fields, invalid milestone transitions, contradictory retry counts or generations, and blocker/milestone combinations that cannot occur in the workflow.

## Recovery

A normal `run` journals the complete captured window, its run ID, and planned task IDs in `repository.json.pending_window` before advancing the marker cursor. Re-entry reuses that journal instead of sending another marker or minting new IDs; a marker sent just before a crash is also detected and reused. After all `task_created` events are durable, the cursor advances and the pending window clears in one repository-metadata replacement.

The run then reconciles task and raw-intake projections from committed events and resumes executable tasks after their last committed milestone. It never calls the draft adapter again after `draft_delivery_confirmed`. If a previous process left a run in `processing`, the next mutating run records it as `interrupted`, links it through `recovered_by_run`, and generates an interruption report before continuing.

`--simulate-interruption-after <milestone>` is a validation-only scripted-adapter option. Do not use it for an operator's production task.

## Retry

Retry policy is centralized by operation and error category. The current `deliver_draft` transient-error budget is a scripted-fixture value for core validation, not a production decision. A normal run executes `retry_pending`, skips `retry_exhausted`, and skips `permanent_failure`. Use:

```text
python scripts/process_weixin_submissions.py retry \
  --repository <task-repository> \
  --task-id <retry-exhausted-task-id>
```

This creates an auditable retry run, increments the task's retry generation, and changes the blocker back to `retry_pending`. It does not itself call the Blog adapter; the next normal `run` performs that attempt.

## Writer lock and status

Every mutating operation acquires `<task-repository>/writer.lock`. Never delete or replace a lock merely because its process looks old. Report the lock owner and ask the operator to investigate it. `status` does not acquire the writer lock and must not modify repository files, so it remains safe while another run holds the lock.
