# 本地任务库目录

本地任务库独立于 Skill 和 Git 仓库。`runs/` 保存一次 Agent 执行的审计记录，`tasks/` 保存跨多次运行持续存在的投稿任务；两者通过 ID 引用，不互相嵌套或复制数据。

```text
weixin-blog-publish-data/
├── repository.json
├── config.json
├── locks/
│   └── run.lock
├── runs/
│   ├── run_01JABC.../
│   │   ├── run.json
│   │   ├── events.jsonl
│   │   └── report.md
│   └── run_01JDEF.../
│       ├── run.json
│       ├── events.jsonl
│       └── report.md
├── tasks/
│   ├── task_01JABC.../
│   │   ├── task.json
│   │   ├── events.jsonl
│   │   ├── raw/
│   │   │   ├── intake/
│   │   │   │   ├── task-header.txt
│   │   │   │   └── article-card.json
│   │   │   └── source-01/
│   │   │       ├── clipboard.txt
│   │   │       ├── source-url.txt
│   │   │       ├── capture-manifest.json
│   │   │       ├── images/
│   │   │       │   ├── 001.png
│   │   │       │   └── 002.jpg
│   │   │       └── screenshots/
│   │   │           └── image-003-viewport.png
│   │   ├── sources/
│   │   │   └── source-01/
│   │   │       ├── article.md
│   │   │       ├── source.json
│   │   │       └── images/
│   │   │           ├── 001.json
│   │   │           ├── 002.json
│   │   │           ├── 003.json
│   │   │           └── 003.png
│   │   ├── work/
│   │   │   └── rewrite/
│   │   │       ├── article.md
│   │   │       └── manifest.json
│   │   └── delivery/
│   │       ├── request.json
│   │       ├── response.json
│   │       └── result.json
│   └── task_01JXYZ.../
│       └── ...
└── tmp/
```

## Relationships

- `run.json` records the tasks created and attempted during that run.
- `task.json` records only the run that originally created the task.
- Every task event and attempt records the run in which it occurred.
- A task's complete run history is derived from `events.jsonl`; it is not duplicated in the task snapshot.
- An input window belongs to a normal `run` and is recorded inside `run.json`; it is not a separate directory.

## Storage boundaries

- `raw/` is immutable evidence.
- `sources/` is rebuildable from `raw/`.
- A validated rewrite artifact is immutable after it is committed.
- `delivery/request.json` is regenerated from the rewrite artifact and the real Blog adapter.
- `report.md` is regenerated from the run record and event history.
- `tmp/` contains uncommitted atomic-write or attempt data and is empty when idle.
- Schema definitions, prompts, migrations and executable scripts live in the canonical Skill, not in the task repository. Data files record the versions and hashes that produced them.

