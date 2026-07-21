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
      "author": {
        "name": "Public author name"
      },
      "postType": "opinion",
      "category": "Community"
    }
  }
}
```

New targets use the deployed preferred `author` object with required `name`, plus optional `slug`, `title`, and `orgSlug`. Blog API v0.6 matches authors by the exact `author.name`; changing the name may therefore create or select a different Blog author. Surrounding whitespace and control characters are rejected instead of being normalized into a possibly different identity. `externalId` and `authorExternalId` are obsolete and rejected in new target mappings and management changes. For recovery compatibility only, the adapter removes either obsolete field from a historical fixed v0.5 publication request before sending it. Legacy target records may still use non-empty `authorName`. The nested object cannot be combined with legacy flat author fields, preventing ambiguous identity precedence. Other optional mapping fields are `authorSlug`, `authorTitle`, `orgSlug`, `orgName`, `postType`, `category`, `featured`, and `tags`. The API key value comes only from the named environment variable; the request artifact contains no secret.

The Blog default is now `postType: opinion`; the checked-in LSForum target sets it explicitly so publication behavior does not depend on a remote default. This Skill does not synthesize or send `excerpt`, so the Blog displays no lead quote; v0.6 no longer derives one from the Markdown body.

The environment value must be unquoted printable ASCII without surrounding whitespace. Shell syntax may use normal ASCII quotes to assign the value, but those quote characters must not become part of the value. Invalid formatting is reported as `needs_configuration` before any Blog request.

LSForum creation supports `draft | published`, but this Skill's `auto` path is explicitly public. The run workflow uses only:

- authenticated `GET /posts/<slug>?manage=true` for preflight and confirmation;
- authenticated `POST /posts` with `status: published` for explicit publication.

Successful publication retains the current integer `version` and HTTP `ETag` in the normalized result. If a lost POST response is recovered through management GET and that GET omits an ETag header, the adapter records the contract-equivalent `"<version>"` concurrency token accepted by the version header. The LSForum adapter also contains narrow explicit methods for authenticated management GET, conditional PATCH, soft delete, restore, and read-only revisions so it matches the external Content API. They are not exposed as Skill operations, WeChat fields, normal-run steps, or recovery actions. The Skill has no hard-delete, history-mutation, user-management, deployment, or arbitrary-request capability.

PATCH requires a caller-supplied current version and sends `X-Post-Version: "<version>"`, as specified by deployed OpenAPI v1.2.0. Nested and legacy flat author representations are mutually exclusive here as well. A missing/invalid header is `428`; a stale version is `412` / `blog_version_conflict` and is never retried automatically. DELETE means soft delete only; restore uses the dedicated endpoint, revisions are read-only, and permanent deletion remains an administrator-only database action.

Every publication fixes its ID, slug, content task, rewrite commit hash, target mapping, adapter destination, and complete request before POST. Recovery verifies the request bytes against every attempt copy and marker hash, then verifies the task, rewrite commit, target, title, body, images, adapter, and destination before any external action. A successful response is retained raw, including the ETag response header, and normalized to the public slug, URL, content status, version, and ETag. Local images without stable public URLs produce `needs_configuration` before any request is sent.

An operator may later explicitly authorize a text-only version of an existing validated rewrite with `publish --image-policy omit`. This does not alter raw evidence, structured source, or the committed rewrite. The independent publication aggregate records an immutable presentation policy, the number of removed Markdown image embeds, and hashes of both source and published bodies. The default `preserve` policy retains the local-image safety block.

For a public version with images, use `publish --image-policy upload --cover-image source-image-NNN.ext --env-file .env`. The operation uploads only local image references present in the validated Markdown; captured but unused images are not uploaded. Before the first Blob side effect it commits a content-addressed plan containing source hashes, stable pathnames, destination identity, and the explicit cover selection. JPEG, PNG, WebP, and GIF are accepted up to 10 MB each, with at most 20 local references. Returned URLs must be HTTPS Public Vercel Blob URLs. The resolved presentation then fixes every Markdown replacement, ordered URL list, cover URL, and source/published body hash before the Blog POST. The cover is sent as Blog `image`; inline images remain Markdown URLs.

The real uploader uses the pinned official Vercel Python SDK, reads `BLOB_READ_WRITE_TOKEN` only at runtime, and records `BLOB_STORE_ID` as the non-secret destination identity. The publication also fixes the Blog adapter destination before any image upload. Local `.env` loading does not invoke a shell, expand variables, or persist secrets; values in the explicitly selected file override stale ambient values. Tests use an isolated fake Blob boundary. Content-addressed pathnames use overwrite only for the same source hash, so retrying the same bytes does not create a different logical asset URL. Every completed image upload is recorded immediately and hash-anchored by an append-only publication event. Recovery requires the exact planned content type and a URL accepted by the fixed Blob destination; an interrupted `publication_created` aggregate resumes its fixed image plan and reuses only anchored records before preparing the Blog request.

Attempt evidence distinguishes `prepared` from `send_started`. A later explicit `auto` run may resume the same fixed publication when `prepared` exists and no send-start marker exists. Once a send-start marker exists, recovery is confirmation-only: it performs authenticated management GET, confirms an exact title/body/author match plus an explicitly represented undeleted `published` state, and never issues another POST. Absence of a recognized deletion-state field is ambiguous and does not count as undeleted. A missing, draft, deleted, ambiguous, or conflicting slug becomes `outcome_unknown`. Legacy requests without a fixed destination fail integrity validation without making either GET or POST requests.

LSForum currently has no idempotency key. Before POST, the adapter checks the fixed slug. After a transport interruption or 5xx, it checks the slug again. If matching content is visible, the result is recovered; otherwise the publication becomes `outcome_unknown` and must not be automatically POSTed again.

Use the real adapter only with an operator-approved target. Automated tests use a localhost HTTP fixture. Separate controlled live acceptance evidence is recorded in [../../../docs/validation/2026-07-17-lsforum-live-acceptance.md](../../../docs/validation/2026-07-17-lsforum-live-acceptance.md).
