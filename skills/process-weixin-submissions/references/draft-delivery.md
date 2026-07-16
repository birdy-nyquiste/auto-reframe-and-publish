# Draft delivery contract

The current core adapter is a fake external service used to validate the delivery boundary. It does not define or predict the real Blog API.

## Capability boundary

`DraftBlogAdapter` exposes exactly three external-effect operations:

- map one opaque publication target to an external target;
- upload one integrity-checked, content-addressed image;
- create or recover one idempotent draft.

There is no public publish, delete, user-management, deployment, arbitrary-request, or arbitrary-file capability. A successful Skill run creates a draft only.

Adapter identity and raw-response normalization are also behind this protocol, so fake or future real response shapes never leak into the canonical delivery module. Transport and validation failures use the typed `BlogErrorCategory` vocabulary before they enter task blockers.

## Generated request

The deterministic delivery module reloads the committed rewrite artifact, uploads each unique image by SHA-256, preserves image occurrence order, and derives `delivery/request.json`. The request is validated by `delivery-request.schema.json` and uses the task ID as its stable idempotency key.

The request is a read-only projection, not an editing source. If it is missing, a later run can rebuild the same bytes from the canonical rewrite artifact and adapter mapping. If it exists with different bytes, delivery stops permanently rather than overwriting or sending it.

Every send attempt also stores its exact request under `delivery/attempts/<run_id>/request.json`.

## Idempotency and uncertain outcomes

The fake service stores an idempotency record before returning acceptance. Repeating the same task key and identical request returns the original draft; reusing the key with different request bytes is rejected. Image uploads use their content hash as identity, so repeated occurrences and retries do not duplicate assets.

An acceptance followed by timeout leaves the task at `rewrite_artifact_ready` with a retry blocker. The next run recovers the original draft through the same key. A task reaches `draft_delivery_confirmed` only after a validated acceptance response and external draft ID are persisted locally.

## Response evidence

- `delivery/attempts/<run_id>/response-raw.json` retains any response before it is trusted.
- `delivery/attempts/<run_id>/error.json` records typed transport, rejection, or validation failure evidence.
- `delivery/response-raw.json` stores the accepted external response exactly.
- `delivery/response.json` stores the Schema-validated normalized response used by task state.

Explicit rejection, unknown fields, non-HTTPS preview locations, and response-like instructions are never treated as acceptance. Invalid responses cannot change local targets or invoke additional Blog capabilities, and one failed task does not stop the remaining queue.
