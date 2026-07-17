# Opt-in publication contract

Publication is a run-level trusted choice, never a WeChat field. Omitted or explicit `--publication none` stops after committed rewrite artifacts and performs no Blog read or write. `--publication auto` creates independent publication aggregates only for content tasks newly completed in that run.

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

LSForum publication is immediate and public. The adapter implements only:

- unauthenticated `GET /posts/<slug>` for preflight and confirmation;
- authenticated `POST /posts` for explicit publication.

There is intentionally no DELETE, edit, user-management, deployment, or arbitrary-request capability.

Every publication fixes its ID, slug, content task, rewrite commit hash, target mapping, and complete request before POST. A successful response is retained raw and normalized to the public slug and URL. Local images without stable public URLs produce `needs_configuration` before any request is sent.

LSForum currently has no idempotency key. Before POST, the adapter checks the fixed slug. After a transport interruption or 5xx, it checks the slug again. If matching content is visible, the result is recovered; otherwise the publication becomes `outcome_unknown` and must not be automatically POSTed again.

Use the real adapter only with an operator-approved target. Current automated tests use a localhost HTTP fixture and do not prove production acceptance.
