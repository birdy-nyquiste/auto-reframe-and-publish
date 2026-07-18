# Opt-in publication contract

Publication is a run-level trusted choice, never a WeChat field. Omitted or explicit `--publication none` stops after committed rewrite artifacts and performs no Blog read or write. `--publication auto` creates independent publication aggregates only for content tasks newly completed in that run; it may also resume an already-created publication whose original authorized attempt was interrupted.

The fake adapter is for core validation. The LSForum adapter reads a non-secret JSON configuration:

```json
{
  "config_version": 1,
  "adapter": "lsforum",
  "base_url": "https://blog-lsforum.vercel.app/api/v1",
  "api_key_env": "LSFORUM_INGEST_API_KEY",
  "targets": {
    "local-target-id": {
      "authorName": "Public author name",
      "category": "Community"
    }
  }
}
```

`authorName` is required for each target. Allowed optional mapping fields are `authorTitle`, `orgName`, `postType`, `category`, `featured`, and `tags`. The API key value comes only from the named environment variable; the request artifact contains no secret.

The environment value must be unquoted printable ASCII without surrounding whitespace. Shell syntax may use normal ASCII quotes to assign the value, but those quote characters must not become part of the value. Invalid formatting is reported as `needs_configuration` before any Blog request.

LSForum creation supports `draft | published`, but this Skill's `auto` path is explicitly public. The run workflow uses only:

- authenticated `GET /posts/<slug>?manage=true` for preflight and confirmation;
- authenticated `POST /posts` with `status: published` for explicit publication.

Successful publication retains the current integer `version` and HTTP `ETag` in the normalized result. If a lost POST response is recovered through management GET and that GET omits an ETag header, the adapter records the contract-equivalent `"<version>"` concurrency token required by `If-Match`. The LSForum adapter also contains narrow explicit methods for authenticated management GET, conditional PATCH, soft delete, restore, and read-only revisions so it matches the external Content API. They are not exposed as Skill operations, WeChat fields, normal-run steps, or recovery actions. The Skill has no hard-delete, history-mutation, user-management, deployment, or arbitrary-request capability.

PATCH requires a caller-supplied current version and sends `If-Match: "<version>"`. A `412` is `blog_version_conflict` and is never retried automatically. DELETE means soft delete only; restore uses the dedicated endpoint, revisions are read-only, and permanent deletion remains an administrator-only database action.

Every publication fixes its ID, slug, content task, rewrite commit hash, target mapping, adapter destination, and complete request before POST. Recovery verifies the request bytes against every attempt copy and marker hash, then verifies the task, rewrite commit, target, title, body, images, adapter, and destination before any external action. A successful response is retained raw, including the ETag response header, and normalized to the public slug, URL, content status, version, and ETag. Local images without stable public URLs produce `needs_configuration` before any request is sent.

Attempt evidence distinguishes `prepared` from `send_started`. A later explicit `auto` run may resume the same fixed publication when `prepared` exists and no send-start marker exists. Once a send-start marker exists, recovery is confirmation-only: it performs authenticated management GET, confirms an exact title/body/author match plus an explicitly represented undeleted `published` state, and never issues another POST. Absence of a recognized deletion-state field is ambiguous and does not count as undeleted. A missing, draft, deleted, ambiguous, or conflicting slug becomes `outcome_unknown`. Legacy requests without a fixed destination fail integrity validation without making either GET or POST requests.

LSForum currently has no idempotency key. Before POST, the adapter checks the fixed slug. After a transport interruption or 5xx, it checks the slug again. If matching content is visible, the result is recovered; otherwise the publication becomes `outcome_unknown` and must not be automatically POSTed again.

Use the real adapter only with an operator-approved target. Automated tests use a localhost HTTP fixture. Separate controlled live acceptance evidence is recorded in [../../../docs/validation/2026-07-17-lsforum-live-acceptance.md](../../../docs/validation/2026-07-17-lsforum-live-acceptance.md).
