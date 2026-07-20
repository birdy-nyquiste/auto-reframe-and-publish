# 本地任务库目录

本地任务库独立于 Skill 和 Git 仓库。`runs/` 保存一次 Agent 执行的审计记录，`tasks/` 保存投稿与改写任务，`publications/` 保存独立的公开发布任务；三者通过 ID 引用，不互相嵌套或复制数据。

当前持久库版本为 v3；旧版本不与 v3 混读，迁移尚未实现。

```text
weixin-blog-publish-data/
├── repository.json
├── writer.lock                         # 仅在可变操作执行期间存在
├── runs/
│   ├── run_01JABC.../
│   │   ├── run.json
│   │   └── report.md
│   └── run_01JDEF.../
│       ├── run.json
│       └── report.md
├── tasks/
│   ├── task_01JABC.../
│   │   ├── task.json
│   │   ├── events/
│   │   │   ├── 000001-event_....json
│   │   │   └── 000002-event_....json
│   │   ├── raw/
│   │   │   ├── intake.json
│   │   │   ├── capture/
│   │   │       ├── manifest.json
│   │   │       ├── clipboard.txt
│   │   │       ├── assets/
│   │   │       │   └── <sha256>        # 原图、裁剪图或 GIF 静态帧
│   │   │       └── viewports/
│   │   │           └── <sha256>        # 截图降级时的未修改视口证据
│   │   │   └── capture-attempts/
│   │   │       └── <run_id>/           # 未通过完整性/适用性门槛的不可变尝试
│   │   │           ├── manifest.json
│   │   │           └── ...
│   │   ├── sources/
│   │   │   └── article.json
│   │   ├── rewrite/
│   │   │   ├── content.md
│   │   │   ├── manifest.json
│   │   │   ├── commit.json
│   │   │   └── attempts/
│   │   │       └── <run_id>/
│   │   │           ├── input.json
│   │   │           ├── candidate.md     # 生成成功或验证失败时存在
│   │   │           ├── candidate-manifest.json
│   │   │           └── failure.json     # 生成或验证失败时存在
│   │
│   └── task_01JXYZ.../
│       └── ...
├── publications/
│   ├── publication_01JABC.../
│   │   ├── publication.json
│   │   ├── events/
│   │   │   ├── 000001-event_....json
│   │   │   └── 000002-event_....json
│   │   ├── request.json               # 请求生成成功时存在
│   │   ├── response-raw.json          # 确认成功时存在
│   │   ├── response.json              # 标准化公开结果
│   │   └── attempts/
│   │       └── <run_id>/
│   │           ├── request.json
│   │           ├── response-raw.json
│   │           └── error.json
│   └── publication_01JXYZ.../
│       └── ...
```

这是当前脚本化适配器和 `macos_computer_use_v1` captured-window 共同写出的目录。媒体文件采用 SHA-256 内容寻址且不依赖扩展名；MIME 类型、文章内出现顺序、采集方法、降级信息和哈希都保存在 `manifest.json`。相同字节只保存一次，但每次文章内出现仍有独立清单项。真实 macOS Computer Use 负责生成待验证窗口，不会改变三个聚合的同级关系。

## Relationships

- `run.json` records the tasks created and attempted during that run.
- `run.json` also records the trusted publication selection and publication IDs created and attempted during that run.
- `task.json` records only the run that originally created the task.
- Every task event and attempt is one append-only JSON file and records the run in which it occurred. State-changing events carry the validated post-commit task state and form the atomic write-ahead record; `task.json` is reconciled from them after interruption.
- A task's complete run history is derived from `events/`; it is not duplicated in the task snapshot.
- A publication references exactly one task and its immutable rewrite commit. Publication progress, blockers and external results never mutate task state.
- An input window belongs to a normal `run` and is recorded inside `run.json`; it is not a separate directory.
- Before its task registrations finish, the same complete window and its fixed run/task IDs live in `repository.json.pending_window`; advancing the marker cursor and clearing that journal is one atomic metadata replacement.

## Storage boundaries

- `raw/` is immutable evidence after its milestone is committed.
- An incomplete or unusable capture is retained under `raw/capture-attempts/<run_id>/`; it never occupies or mutates the canonical `raw/capture/` paths.
- `raw/capture/clipboard.txt` is copied text, never OCR reconstruction. A missing source URL is allowed when the body, static images and article-end evidence are complete.
- Screenshot fallback preserves both the cropped static asset and the unmodified viewport screenshot; GIF stores one static frame and a degradation warning. Video and audio are neither downloaded nor transcribed.
- `sources/article.json` is rebuildable from `raw/capture/manifest.json` and hash-verified evidence.
- A validated rewrite artifact is immutable after it is committed; `rewrite/commit.json` independently anchors the exact manifest bytes.
- Rewrite attempts explicitly separate trusted task controls from hash-addressed untrusted sources. The Agent output pair remains under `rewrite/attempts/<run_id>/`; deterministic validation commits the exact pair. Failed generations or validations never occupy the committed artifact paths.
- The committed rewrite manifest records content, source, image, policy, prompt and Schema hashes. It contains no Blog request, response or publication state.
- `publications/<id>/request.json` is a Schema-validated, read-only projection from one committed rewrite and adapter target mapping. A conflicting existing file is rejected rather than overwritten.
- Publication attempts retain the exact request and either untrusted raw response or typed error evidence. Only a validated public result is copied to canonical response files and committed into publication state.
- Local images without stable public URLs block publication before request generation; they are never silently removed.
- `report.md` is regenerated from the run record and event history.
- Atomic writes use same-directory temporary files that disappear after replacement.
- `writer.lock` applies to every mutable operation. Status reports it but never deletes or replaces it, even when it appears stale.
- Schema definitions, prompts, migrations and executable scripts live in the canonical Skill, not in the task repository. Data files record the versions and hashes that produced them.
