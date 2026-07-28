# Opt-in publication contract

Publication is a run-level trusted choice, never a WeChat field. Omitted or explicit `--publication none` stops after committed rewrite artifacts and performs no Blog read or write. `--publication auto` creates independent publication aggregates only for content tasks newly completed in that run; it may also resume an already-created publication whose original authorized attempt was interrupted. `run --publication auto --image-policy upload --env-file .env` uses the same durable image-upload boundary as explicit `publish`, so a newly generated artifact with local image references can be uploaded and published in one run.

The fake adapter is for core validation. The LSForum adapter reads a non-secret JSON configuration:

```json
{
  "config_version": 1,
  "adapter": "lsforum",
  "base_url": "https://blog-lsforum.vercel.app/api/v1",
  "api_key_env": "LSFORUM_INGEST_API_KEY"
}
```

The task header supplies the Blog fields directly. `author.name` is required; optional safe fields are `author.slug`, `postType`, `category`, `featured`, and `tags`. Blog API v0.7 matches authors by the exact `author.name`; changing the name may therefore create or select a different Blog author. The API no longer declares `author.title`, `author.orgSlug`, `orgSlug`, or `orgName`; new intake rejects them rather than relying on ignored historical fields. Surrounding whitespace and control characters are rejected instead of being normalized into a possibly different identity. The project stores these typed fields with the task for audit and request recovery, but maintains no local author/target mapping. `externalId`, `authorExternalId`, and legacy flat author fields are rejected for new intake. The API key value comes only from the named environment variable; the request artifact contains no secret.

If publication behavior must not depend on the remote default, the sender should include `postType: opinion` in `#投稿`. This Skill does not synthesize or send `excerpt`, so the Blog displays no lead quote; v0.6 no longer derives one from the Markdown body.

The environment value must be unquoted printable ASCII without surrounding whitespace. Shell syntax may use normal ASCII quotes to assign the value, but those quote characters must not become part of the value. Invalid formatting is reported as `needs_configuration` before any Blog request.

LSForum upload supports `draft | published`, but this Skill's `auto` path is explicitly public. The run workflow uses only:

- public `GET /posts/<slug>` for preflight and confirmation;
- authenticated `POST /posts` with `status: published` for explicit publication.

Successful POST responses retain the integer `version` when Blog returns it. Public recovery responses do not expose a management version or ETag, so recovered results intentionally omit both. Blog v0.7 exposes no public update, delete, restore, revisions, or management-read operation, and the adapter provides none.

Every publication fixes its ID, slug, content task, rewrite commit hash, direct Blog publication fields, adapter destination, and complete request before POST. Recovery verifies the request bytes against every attempt copy and marker hash, then verifies the task, rewrite commit, publication fields, title, body, images, adapter, and destination before any external action. A successful response is retained raw and normalized to the public slug, URL, content status, and optional POST version. Local images without stable public URLs produce `needs_configuration` before any request is sent.

An operator may later explicitly authorize a text-only version of an existing validated rewrite with `publish --image-policy omit`. This does not alter raw evidence, structured source, or the committed rewrite. The independent publication aggregate records an immutable presentation policy, the number of removed Markdown image embeds, and hashes of both source and published bodies. The default `preserve` policy retains the local-image safety block.

For a new public version with images, use `run --publication auto --image-policy upload --env-file .env` or `publish --image-policy upload --env-file .env`. Artifact v2 supplies the Agent-selected cover directly, including an explicit no-cover choice; every manual cover argument is rejected for v2. `--cover-image source-image-NNN.ext` remains available only to publish a legacy artifact v1 that predates persisted cover selection. The operation uploads only local image references present in the validated Markdown; captured but unused images are not uploaded. Before the first Blob side effect it commits a content-addressed plan containing source hashes, stable pathnames, destination identity, and the explicit cover selection. JPEG, PNG, WebP, and GIF are accepted up to 10 MB each, with at most 20 local references. Returned URLs must be HTTPS Public Vercel Blob URLs. The resolved presentation then fixes every Markdown replacement, ordered URL list, cover URL, and source/published body hash before the Blog POST. The cover is sent as Blog `image`; inline images remain Markdown URLs.

The real uploader uses the pinned official Vercel Python SDK, reads `BLOB_READ_WRITE_TOKEN` only at runtime, and records `BLOB_STORE_ID` as the non-secret destination identity. The publication also fixes the Blog adapter destination before any image upload. Local `.env` loading does not invoke a shell, expand variables, or persist secrets; values in the explicitly selected file override stale ambient values. Tests use an isolated fake Blob boundary. Content-addressed pathnames use overwrite only for the same source hash, so retrying the same bytes does not create a different logical asset URL. Every completed image upload is recorded immediately and hash-anchored by an append-only publication event. Recovery requires the exact planned content type and a URL accepted by the fixed Blob destination; an interrupted `publication_created` aggregate resumes its fixed image plan and reuses only anchored records before preparing the Blog request.

Attempt evidence distinguishes `prepared` from `send_started`. A later explicit `auto` run may resume the same fixed publication when `prepared` exists and no send-start marker exists. Once a send-start marker exists, recovery is confirmation-only: it performs the public detail GET, confirms an exact slug/title/body/author/cover match, and never issues another POST. Because the public endpoint exposes only published, non-deleted content, a matching response is sufficient publication evidence. A missing or conflicting slug becomes `outcome_unknown`. Legacy requests without a fixed destination fail integrity validation without making either GET or POST requests.

LSForum currently has no idempotency key. Before POST, the adapter checks the fixed slug through the public detail endpoint. After a transport interruption or 5xx, it checks the slug again. If matching content is publicly visible, the result is recovered; otherwise the publication becomes `outcome_unknown` and must not be automatically POSTed again. A conflicting unpublished record cannot be inspected through v0.7 and is therefore never treated as recovered.

Use the real adapter only with operator-approved publication fields. Automated tests use a localhost HTTP fixture. Separate controlled live acceptance evidence is recorded in [../../../docs/validation/2026-07-17-lsforum-live-acceptance.md](../../../docs/validation/2026-07-17-lsforum-live-acceptance.md).
