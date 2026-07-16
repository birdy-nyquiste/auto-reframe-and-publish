# 本地任务库目录

本地任务库独立于 Skill 和 Git 仓库。`runs/` 保存一次 Agent 执行的审计记录，`tasks/` 保存跨多次运行持续存在的投稿任务；两者通过 ID 引用，不互相嵌套或复制数据。

当前持久库版本为 v2；v1 是持久事件日志落地前的 tracer 格式，不与 v2 混读。

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
│   │   │   └── submission.json
│   │   ├── sources/
│   │   │   └── article.json
│   │   ├── rewrite/
│   │   │   ├── content.md
│   │   │   └── manifest.json
│   │   └── delivery/
│   │       ├── request.json
│   │       └── response.json
│   └── task_01JXYZ.../
│       └── ...
```

这是当前 `core_validated` 脚本适配器实际写出的目录。完整 Windows 采集后增加的原图、视口证据、哈希和采集清单将在对应采集 Ticket 中扩展，但不会改变 `runs/` 与 `tasks/` 的同级关系。

## Relationships

- `run.json` records the tasks created and attempted during that run.
- `task.json` records only the run that originally created the task.
- Every task event and attempt is one append-only JSON file and records the run in which it occurred. State-changing events carry the validated post-commit task state and form the atomic write-ahead record; `task.json` is reconciled from them after interruption.
- A task's complete run history is derived from `events/`; it is not duplicated in the task snapshot.
- An input window belongs to a normal `run` and is recorded inside `run.json`; it is not a separate directory.
- Before its task registrations finish, the same complete window and its fixed run/task IDs live in `repository.json.pending_window`; advancing the marker cursor and clearing that journal is one atomic metadata replacement.

## Storage boundaries

- `raw/` is immutable evidence after its milestone is committed.
- `sources/` is rebuildable from `raw/`.
- A validated rewrite artifact is immutable after it is committed.
- `delivery/request.json` is regenerated from the rewrite artifact and the real Blog adapter.
- `report.md` is regenerated from the run record and event history.
- Atomic writes use same-directory temporary files that disappear after replacement.
- `writer.lock` applies to every mutable operation. Status reports it but never deletes or replaces it, even when it appears stale.
- Schema definitions, prompts, migrations and executable scripts live in the canonical Skill, not in the task repository. Data files record the versions and hashes that produced them.
