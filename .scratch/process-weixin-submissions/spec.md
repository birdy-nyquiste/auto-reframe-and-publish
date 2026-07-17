# Process Weixin Submissions

Status: needs-triage

> 发布相关设计已被 [ADR-0009](../../docs/adr/0009-separate-content-work-from-opt-in-publication.md) 取代：投稿任务与发布任务将分离，`run` 默认不发布，只有操作人本次明确选择自动发布才调用即时公开接口。采集和改写要求仍然有效；在继续发布实现前必须修订本 spec 及相关 tickets。

## Problem Statement

The team receives WeChat Official Account articles through one operational WeChat account's File Transfer Assistant and needs a reliable way to turn those submissions into draft articles for an external Nyquiste Blog service. Continuous monitoring and polling are too fragile, unstructured chat messages are ambiguous, desktop capture is stateful, and a single failure must not interrupt unrelated submissions. The process must remain manually triggered, auditable, resumable, portable between Codex and Claude Code, and unable to publish publicly without Blog-admin approval.

## Solution

Build one repository-owned, user-invoked Skill that runs locally on a fixed Windows collection host. Each explicit `run` sends one minimal boundary marker through Computer Use, treats the messages between adjacent markers as its input window, records new submissions in a file-backed task repository, resumes historical work, captures article text and static images, uses the running Agent to produce a validated rewrite artifact, and submits that artifact to the external Blog service as a draft through a capability-limited adapter.

The Skill exposes four operations: initialize, run, status, and retry. Core logic is agent-neutral and deterministic scripts own state mutations, validation, locking, task parsing, repository writes, report generation, and Blog request construction. Computer Use performs desktop gestures and evidence capture. Source content is untrusted data and cannot control the Agent. Public publication remains exclusively in the external Blog administration interface.

## User Stories

1. As an operator, I want to explicitly initialize the Skill, so that it creates a local task repository and establishes a clean WeChat baseline without importing old chat history.
2. As an operator, I want to explicitly run one end-to-end processing cycle, so that the Agent never starts desktop automation merely because WeChat is mentioned in conversation.
3. As a submitter, I want a small fixed task header, so that I can submit work without learning an automation protocol.
4. As a submitter, I want to specify an opaque publication target, so that the WeChat template does not depend on the external Blog API resource model.
5. As a submitter, I want to omit the requirements field, so that the standard rewrite policy is used automatically.
6. As a submitter, I want to provide multiline requirements when needed, so that a task can express custom editorial direction.
7. As an operator, I want a task header to pair only with the immediately following article card, so that the Agent never guesses message ownership.
8. As an operator, I want the first version to accept only forwarded Official Account article cards, so that one source workflow can become dependable before more types are added.
9. As an operator, I want every submission occurrence to create a distinct task, so that intentionally repeated content is not mistaken for a retry.
10. As an operator, I want one minimal WeChat boundary marker per run, so that input windows are deterministic without filling the chat with status messages.
11. As an operator, I want messages arriving after the current boundary marker to remain for the next run, so that work arriving during processing is never lost.
12. As an operator, I want new tasks safely recorded before content processing begins, so that an interruption cannot lose a discovered submission.
13. As an operator, I want historical executable tasks and new tasks processed oldest first, so that neither backlog nor new work starves.
14. As an operator, I want one task failure isolated from the rest of the run, so that the run continues to a clear result for every attempted task.
15. As an operator, I want incomplete inputs preserved as needs-input tasks, so that missing information is visible and auditable.
16. As a submitter, I want to resubmit an incomplete task as a new complete task, so that the WeChat protocol does not need correction commands or task IDs.
17. As an operator, I want Official Account body text captured through copy and paste, so that OCR errors do not become source facts.
18. As an operator, I want a missing source URL to be non-fatal when complete text and images are available, so that WeChat's closed behavior does not block useful automation.
19. As an editor, I want every body image captured in original order, so that image-dependent context is available to the content model.
20. As an editor, I want duplicate image bytes stored once without losing their repeated positions, so that storage is efficient without changing article structure.
21. As an editor, I want the first version to use only static images, so that GIF, video, and audio complexity does not undermine capture reliability.
22. As an editor, I want image-only media limitations recorded, so that the Agent never invents unobserved video or audio content.
23. As a maintainer, I want raw evidence immutable, so that parsing and content logic can be improved without recapturing WeChat.
24. As a maintainer, I want structured sources rebuildable from raw evidence, so that source parsing can evolve safely.
25. As a maintainer, I want rewrite content represented as Markdown plus a Schema-validated manifest, so that prose and machine metadata have clear responsibilities.
26. As a maintainer, I want validated rewrite artifacts immutable after commit, so that later delivery attempts always refer to known content.
27. As a maintainer, I want API requests generated from canonical rewrite artifacts, so that request JSON is never an alternate editing source.
28. As an editor, I want the running Codex or Claude Code Agent to understand text and local images, so that no second LLM provider or credential chain is required.
29. As a security owner, I want only task-header fields to control the Agent, so that article text, images, links, and QR codes cannot inject instructions.
30. As a security owner, I want the Blog client limited to draft and image operations, so that the Skill cannot publish, delete, manage users, or deploy.
31. As a Blog administrator, I want publication approval to remain in the Blog administration interface, so that no WeChat command or Agent action can make a draft public.
32. As an operator, I want task progress represented by durable committed milestones, so that a crash never leaves an ambiguous running state.
33. As an operator, I want blockers separate from progress milestones, so that I can see both how far a task got and why it stopped.
34. As an operator, I want retries budgeted by operation and error category, so that a poisoned task cannot consume an entire run.
35. As an operator, I want retry-exhausted tasks re-enabled only by an explicit retry operation, so that ordinary runs remain bounded.
36. As an operator, I want status to be read-only and avoid Computer Use, so that I can audit the repository safely at any time.
37. As an operator, I want one writer lock for all mutating operations, so that two Agents cannot corrupt WeChat, clipboard, or repository state.
38. As an operator, I want stale locks reported rather than stolen, so that an apparently idle run is never silently overridden.
39. As an auditor, I want every task attempt linked to its run, so that I can reconstruct creation, retry, failure, and completion history.
40. As an auditor, I want machine-readable run records and generated Markdown reports, so that automation and human troubleshooting use the same evidence.
41. As an operator, I want detailed results returned in the Agent session and local report rather than WeChat, so that the intake chat stays minimal.
42. As a security owner, I want configuration and secrets separated, so that credentials never enter tasks, logs, reports, prompts, or Git.
43. As an operator, I want the clipboard exclusively controlled and cleared during a run, so that stale or sensitive content is not captured or sent accidentally.
44. As an operator, I want local data retained without automatic deletion or cloud backup, so that evidence is not silently lost or transmitted.
45. As an operator, I want disk usage reported by status, so that retention remains visible before storage becomes a problem.
46. As a maintainer, I want the canonical Skill stored once in the repository, so that Codex and Claude Code installations cannot drift.
47. As a maintainer, I want core behavior validated on Mac with scripted desktop fixtures and a fake Blog API, so that platform-independent work can proceed before Windows access.
48. As a maintainer, I want the real Windows adapter validated through a supervised acceptance suite, so that desktop automation is never declared ready based on Mac tests.
49. As a maintainer, I want readiness reported in explicit stages, so that core, Windows, and real integration readiness are never conflated.

## Implementation Decisions

- The Blog website is external to this project. The project adapts to the actual API when available and does not invent a speculative service contract.
- The canonical Skill is named `process-weixin-submissions`, is stored once in the repository, and is registered into the selected Agent's discovery location during installation.
- The Skill is user-invoked and supports exactly four branches: initialize, run, status, and retry.
- The production runtime is a fixed Windows host where the operational WeChat account, the running Agent, Computer Use, clipboard, and task repository share one local boundary. Mac is the development environment.
- Initialize creates the repository and sends a baseline marker without scanning older messages.
- A normal run sends its boundary marker before scanning. The messages between the previous and current markers are that run's input window. Messages after the marker belong to the next run.
- The WeChat task header starts with the submission marker, contains one required opaque target field, and may omit the requirements section. Omitted or empty requirements select the default rewrite policy. The requirements block consumes the remainder of the message.
- The first version implicitly expects one immediately adjacent Official Account article card. The protocol reserves an optional article-count field for later multi-source support.
- Unknown task-header fields are not guessed. Missing target or missing adjacent article produces a needs-input blocker.
- Every submission occurrence creates a new task, even when its content matches an earlier task exactly. Idempotency applies only to retries of the same local task.
- Runs and tasks are peer aggregates. A run references tasks created and attempted during that execution. A task records only its creation run, and its events record the run responsible for every attempt.
- The repository is file-backed and independent of the Skill and Git. It stores repository metadata, non-secret configuration, a single writer lock, peer run and task directories, and temporary atomic-write data.
- Each run stores a Schema-validated record, append-only events, and a deterministically generated Markdown report.
- Each task stores a Schema-validated snapshot, append-only events, immutable raw evidence, rebuildable structured sources, an immutable committed rewrite artifact, and delivery artifacts.
- JSON Schema is the single source of truth for every serialized field. Unknown fields and illegal state transitions are rejected. Schema, migration, prompt, and script definitions live in the Skill; data records the relevant versions and hashes.
- The normal task workflow contains five semantic durable milestones: task record created, raw evidence complete, structured source complete, rewrite artifact complete, and external draft delivery confirmed. Final enum names are selected when the Schema is authored.
- Task progress records only the last atomically committed milestone. Active operations are attempts in append-only events and do not create a persisted running state.
- A nullable typed blocker is independent of progress. Its branches cover needs input, retry pending, retry exhausted, and permanent failure with branch-specific required fields.
- Incomplete tasks are not amended. A complete resubmission creates a new task and the old task remains auditable but non-executable.
- Retry policy is centralized by operation and error category. Concrete budgets are configured only after Windows and real API evidence exists.
- Raw capture stores exact task-header text, copied body text, optional source URL, static image assets, fallback viewport evidence, hashes, ordering, methods, and completion evidence. Body OCR is not used.
- Source URL acquisition is best effort. Complete copied text, all article images, the task header, a capture manifest, and observed article end are the first-version evidence gate.
- Every body image has an ordered manifest occurrence. Original bytes are preferred; a cropped static image derived from an unmodified viewport screenshot is the fallback.
- GIF is reduced to a static frame with degradation metadata. Video and audio are neither downloaded nor transcribed. A text-sufficient article continues with warnings; a media-only source fails permanently.
- Computer Use performs UI observation and gestures. Deterministic scripts persist and validate bytes. The running Agent interprets already-persisted text and images and produces the rewrite artifact.
- The Agent's content prompt keeps trusted control fields separate from untrusted source data. Source material cannot alter target, read local files, trigger commands, or widen external actions.
- Rewrite policy and the default rewrite prompt are independent Markdown resources. Their detailed contents remain deliberately unresolved.
- The rewrite artifact consists of Markdown content plus a Schema-validated manifest. Failed generations remain temporary attempts; a validated committed artifact is immutable and has no first-version revision system.
- The external adapter transforms the canonical rewrite artifact into the real Blog API request, uploads images if required, maps the opaque target, injects task idempotency, validates request and response, and stores raw and normalized delivery results.
- Generated delivery requests are read-only and rebuildable. The Agent never hand-edits request JSON.
- The Blog client implements only draft creation, draft update if supported, and necessary image upload. Public publish, deletion, user administration, and deployment are absent even if the credential is overprivileged.
- Blog credentials are runtime secrets supplied by environment or Windows credential storage. WeChat, Agent, and Computer Use login states remain owned by their respective runtimes.
- A task is complete only when the real Blog API confirms durable draft acceptance and the external identifier and response have been persisted. Public publication is outside the task state machine.
- A run records all new tasks before processing, then processes all executable historical and new tasks oldest first. Individual failures do not stop the queue.
- Mutating operations require a repository-wide single writer lock. Live or apparently stale locks are never automatically reclaimed. Status remains read-only.
- The only WeChat output from a normal run is its minimal boundary marker, pasted and sent through Computer Use. Detailed results and preview links remain in the Agent response and local report.
- The Skill exclusively controls and clears the Windows clipboard during mutating runs. It does not preserve the prior clipboard contents.
- Local data is retained indefinitely in the first version. Automatic deletion and cloud backup are absent. Temporary uncommitted data is cleaned after a safe run, and status reports configurable disk-usage warnings.
- Readiness levels are core validated, Windows validated, and ready. Only ready represents a complete usable system.

## Testing Decisions

- The highest automated seam is a complete run against a scripted Computer Use adapter, a temporary file-backed repository, deterministic source fixtures, the running content-processing contract, and a fake Blog API. Tests assert observable repository, run-report, and delivery outcomes rather than internal function calls.
- Protocol tests cover omitted requirements, multiline requirements, unknown fields, missing targets, strict adjacency, unsupported source types, identical repeated submissions, and future article-count parsing compatibility.
- Repository contract tests cover Schema validation, rejection of unknown fields, atomic writes, immutable raw and rewrite artifacts, rebuildable sources and reports, event-to-run linkage, illegal transitions, and migration fixtures.
- Workflow tests cover all five durable milestones, every blocker branch, per-operation retry budgets, retry exhaustion, explicit retry, oldest-first scheduling, single-task isolation, and crash recovery from every milestone.
- Boundary tests cover baseline initialization, messages between markers, messages arriving after the current marker, and absence of historical backfill.
- Capture-adapter fixtures cover copied body text, optional URL, article-end evidence, ordered static images, duplicate image bytes, screenshot fallback, GIF degradation, embedded media warnings, and media-only permanent failure.
- Security tests inject instructions into article text, images, links, QR-like content, and API responses and assert that target, local-file access, commands, and allowed Blog operations do not change.
- Delivery tests use the actual external contract only after it exists. Until then, the fake API verifies request generation, idempotent retry, response persistence, capability allowlisting, and refusal to treat a sent-but-unconfirmed request as complete.
- Lock tests cover live-lock refusal, stale-lock reporting without reclaim, read-only status during a write run, and clipboard cleanup on normal and interrupted exits.
- Windows acceptance is supervised and covers WeChat focus, File Transfer Assistant navigation, boundary-marker send and verification, input-window scanning, strict task pairing, body copy, article-end traversal, static-image capture, safe window restoration, multiple tasks, identical submissions, post-marker exclusion, interruption recovery, prompt-injection isolation, and fake-API end-to-end completion.
- Any dependency on coordinates, window dimensions, accessibility structure, or WeChat chrome is explicitly recorded. A relevant UI or version change invalidates and reruns the affected Windows cases.
- Skill validation checks the canonical Skill package and the installation/registration path for each Agent runtime that is claimed as supported. Compatibility is not claimed for an untested runtime.

## Out of Scope

- Building, hosting, deploying, or administering the Blog website.
- Publicly publishing drafts from the Agent or WeChat.
- Defining a speculative Blog API before the real interface is provided.
- Finalizing the content-rewrite policy or default prompt in this phase.
- Polling, continuous monitoring, scheduled automation, multi-host collection, or Windows failover.
- Reading WeChat history before the initialization baseline.
- Supporting pasted links, chat-history bundles, standalone images, files, mini programs, or video cards as task sources.
- Multi-article tasks in the first version, beyond preserving protocol and storage compatibility.
- OCR reconstruction of article body text.
- Animated-image preservation, video/audio download, transcription, or inference of uncaptured media content.
- Editing an incomplete task in place or automatically linking it to a later submission.
- Rewrite revision histories within one task.
- Automatic data deletion, archival, or cloud backup.
- Deciding concrete retry counts before operational evidence exists.
- Claiming Windows, Codex, Claude Code, or real Blog readiness before the corresponding acceptance level passes.

## Further Notes

- The repository currently contains domain documentation and decisions but no implementation. The first implementation target is `core_validated` on Mac with scripted desktop behavior and a fake Blog API.
- The target field's concrete mapping, external authentication, request shape, response shape, asset upload process, and draft-update semantics remain blocked on the Blog team's real documentation.
- The formal rewrite definition and default prompt already have separate placeholder documents and must be completed before the project can reach `ready`.
- Windows Computer Use is a capability contract rather than a hard-coded Agent tool name. The first real Windows implementation and every materially changed UI path require supervised evidence.
