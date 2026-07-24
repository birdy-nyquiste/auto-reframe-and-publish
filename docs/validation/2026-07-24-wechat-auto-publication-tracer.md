# 2026-07-24 WeChat automatic-publication tracer

## Scope

This supervised tracer exercised one newly submitted Official Account article on
the fixed macOS host. The operator explicitly authorized automatic public
publication. The run used the real WeChat UI, the real Codex generator, the
configured Vercel Blob boundary, and the configured LSForum Blog adapter.

This evidence completes Ticket 11's single-run automatic-publication acceptance
item. It does not by itself satisfy Ticket 08's supervised multi-task matrix,
Ticket 09's formal rewrite-policy approval, or the remaining combined failure
matrix in Ticket 11.

## WeChat boundary and capture

- Previous marker:
  `marker_42854061d64d484985857dec63631d41`
- Current marker:
  `marker_03dd5fdb13f44ae1b0d2f39c7d1e74ee`
- Exactly one `#投稿` header and its immediately following Official Account
  article card occurred between the markers.
- Header: `author.name: birdy-yao`; no `洗稿指令` was supplied, so the versioned
  default prompt applied.
- Article title:
  `Chase Total Checking 银行账户【Checking+Savings一共$900开户奖励】`
- The authoritative 2,193-character body came from selecting and copying the
  article inside the WeChat article window, then pasting it into a temporary
  plain-text surface. No screenshot OCR was used to construct the body.
- The article was visibly traversed to the bottom. WeChat's image viewer showed
  exactly two image occurrences and identified the second as the last image.
- Occurrence 1 was saved as original JPEG bytes.
- Occurrence 2 was an animated GIF; the source GIF was retained in temporary
  evidence and reduced to a PNG static frame. The structured source records
  `animation_removed`.
- The temporary captured window is outside Git at
  `task-repository/tmp/live-2026-07-24-checking/captured-window.json`.
- After completion, the clipboard was replaced with `clipboard-cleared` and a
  disposable plain-text paste verified `verification:clipboard-cleared`.

## End-to-end result

- Run: `run_ad7cb333e89242a7a15d72190f9c9773`
- Task: `task_5638bcf1df784e5eb5b866660ef17a03`
- Publication: `publication_fb30589158da4999978e90793953070a`
- CLI status: `completed`
- Task milestone: `rewrite_artifact_ready`
- Publication selection: `auto`
- Image policy: `upload`
- Publication milestone: `publication_confirmed`
- Public URL:
  <https://blog-lsforum.vercel.app/posts/publication-fb30589158da4999978e90793953070a>
- The public URL returned HTTP 200 after the run.
- The normalized Blog result recorded version `1` and ETag `"1"`.
- The artifact is version 2. The running Agent explicitly selected no cover and
  referenced neither captured image in the final Markdown, so the fixed
  publication request contained zero image URLs and no Blob upload was needed.
  This is the permitted Agent-owned no-image outcome; the captured images remain
  local evidence.
- Local run, task, and publication evidence contained neither secret names nor
  recognized secret-value patterns.
- Run report:
  `task-repository/runs/run_ad7cb333e89242a7a15d72190f9c9773/report.md`
- That immutable run report was produced before a reporter-consistency fix and
  incorrectly retained `real Agent rewrite generation` in its generic
  `Not validated` line. The run JSON correctly omitted that capability and the
  committed manifest records `running_agent_v1`. A regression test now requires
  future reports to use the same filtered capability list as their JSON result.

## Remaining acceptance work

- Ticket 08 still requires a supervised real-WeChat window covering multiple
  tasks, duplicate-content submissions, after-marker exclusion, per-task
  failure isolation, and the remaining interruption combinations.
- Ticket 11 still requires its combined default/custom/failure/retry matrix and
  is still blocked by Ticket 08 and the deferred Ticket 09 formal policy.
- Repository validation therefore remains `core_validated`; this tracer does
  not justify `macos_validated` or `ready`.
