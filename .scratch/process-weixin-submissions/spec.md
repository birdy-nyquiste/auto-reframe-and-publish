# Process Weixin Submissions

Status: ready-for-agent

## Goal

在一台固定 Windows 主机上，由操作人手动触发一个仓库内 Skill，一次读取文件传输助手里自上次边界标记以来的新增投稿，持久化原始证据，生成经验证的改写产物；只有操作人在本次 `run` 中明确选择自动发布时，才把本次新产物交给 Blog 即时公开接口。

采集和内容处理与发布是两个独立流程。投稿任务的完成条件是改写产物已提交；发布任务的完成条件是外部服务已确认公开。发布失败不得改变或回滚投稿任务。

## Operator contract

Skill 只提供四个操作：`initialize`、`run`、`status`、`retry`。

- `initialize` 建立本地任务库和微信边界，不回读旧历史。
- `run` 读取下一个边界窗口，并处理窗口中所有新投稿及可恢复的内容任务。
- `run` 的可信运行参数包含发布选择 `none | auto`；省略等同 `none`。
- `auto` 只作用于本次运行中新到达 `rewrite_artifact_ready` 的投稿任务，不扫描并发布历史产物。
- `status` 只读，不使用 Computer Use，不要求 Blog 凭据。
- `retry` 只重开明确允许重试且已经耗尽预算的本地工作；结果未知的公开 POST 不能通过普通重试再次发送。

微信输入保持最少：一个显式投稿标识、必填目标 ID、可完全省略的要求，以及紧邻的一张公众号文章卡片。要求省略或为空时使用独立 Markdown 文件中的默认策略。每次出现都创建不同投稿任务；第一版每个任务只接受一篇文章，数据模型保留未来多文章扩展空间。

## Aggregates and storage

本地任务库与 Skill 代码、Git 分离，至少包含：

```text
repository.json
runs/<run_id>/
tasks/<task_id>/
publications/<publication_id>/
tmp/
```

Run、投稿任务和发布任务是同级聚合：

- Run 记录输入窗口、运行级发布选择，以及本次创建和尝试的投稿/发布任务 ID。
- 投稿任务保存追加事件、不可变 raw、可重建 sources、不可变 rewrite commit；最终里程碑为 `rewrite_artifact_ready`。
- 发布任务引用 `task_id` 与 rewrite commit，独立保存追加事件、固定请求、每次尝试、原始响应和标准化结果。
- 所有 JSON 字段由 Schema 定义，拒绝未知字段和非法状态转换；投影可由已提交事件恢复。

## Content processing

- Computer Use 负责微信导航、复制粘贴、截图和原始图片获取；剪贴板由运行独占并在所有退出路径清空。
- 正文以复制粘贴文本为准，不以 OCR 结果构造事实。
- 第一版只支持静态图；每次图片出现保留顺序，重复字节可去重。GIF 只保存静态帧并注明降级；视频和音频不下载、不转录。
- raw 证据不可变；sources 可从 raw 重建；改写产物是 Markdown 加 Schema 验证的 manifest，提交后不可变。
- 只有任务头字段是可信控制输入。文章正文、图片、链接、二维码和外部响应都不能改变目标、读取本地文件、执行命令或扩大外部能力。
- “洗稿”的正式定义和默认提示词分别保存在独立 Markdown 文档中；未完成前不宣称正式内容质量验收通过。

## Publication

- Blog 网站本身不在本项目范围内；适配器遵循 `docs/external/lsforum-blog-api-reference.md` 中整理的外部契约。
- `none` 不创建发布任务、不调用 Blog，也不要求凭据。
- `auto` 为本次成功完成内容处理的投稿创建独立发布任务，并逐个执行；一个失败不影响其他任务。
- 目标 ID 通过非敏感本地配置映射为外部 `authorName` 及允许的投稿字段；当前接口未提供稳定 author ID。API key 只从环境或系统凭据存储取得，不能进入 Git、任务、日志、报告或提示。
- 发送前固定 publication ID、slug、rewrite commit 和完整请求。生成请求是 canonical artifact 的只读投影，Agent 不手改 JSON。
- LSForum 创建接口支持 draft/published；`auto` 显式提交 `status: published` 并保存 version 与 ETag。发布确认使用带认证的 `manage=true` 读取。
- 适配器匹配条件 PATCH、软删除、恢复和 revisions 外部能力，但这些不是 Skill operation、微信字段、普通运行步骤或自动恢复动作；客户端不提供彻底删除或历史修改。
- 当前接口没有服务端幂等键。POST 超时或连接中断后先用固定 slug 查询；若仍无法判断，状态为 `outcome_unknown`，禁止自动再次 POST。
- 明确成功保存公开 URL；明确拒绝保存失败证据。含本地图片但缺少稳定公网 URL 时阻塞，不静默丢图，也不猜测上传接口。

## Durable states

投稿任务的正常里程碑为：

1. `task_created`
2. `raw_evidence_ready`
3. `structured_source_ready`
4. `rewrite_artifact_ready`

发布任务使用独立状态机，至少区分：已创建、请求就绪、已确认公开、明确失败、输入不足/配置不足、结果未知和重试耗尽。进度与 blocker 分开；状态名和字段以 Schema 为准。

系统不持久化模糊的 `running` 任务状态。正在执行的操作表现为追加 attempt 事件，任务快照只指向最后一个原子提交的里程碑。写操作由仓库级单 writer lock 保护；疑似陈旧锁只报告，不自动抢占。

## Verification

Mac 自动化测试的最高 seam 是 CLI `run`：使用脚本化微信与剪贴板、临时文件任务库、确定性 Agent 产物，以及 fake 或本地 HTTP Blog fixture，通过任务库、报告和观察到的 HTTP 请求验收行为，不测试私有函数。

必须覆盖：

- 省略要求、默认策略、多行要求、未知字段、缺目标、严格相邻、重复投稿和未来多文章字段兼容。
- 原始文本与静态图证据、图片顺序/去重、媒体降级、不可变性、Schema、事件恢复、锁和剪贴板清理。
- 默认/显式不发布没有任何 Blog 副作用。
- 显式自动发布、目标映射缺失、图片阻塞、公开成功、明确拒绝、超时后查询确认和 `outcome_unknown` 禁止重发。
- 发布状态、version/ETag 持久化、管理 GET 认证、PATCH `X-Post-Version`、428 前置条件、412 版本冲突、软删除、恢复与只读 revisions 的 HTTP 契约。
- 多任务排序与失败隔离、中断后从最后提交里程碑恢复、状态和报告可重建。

Windows Computer Use 和真实 Blog 分别需要监督式验收。Readiness 分为 `core_validated`、`windows_validated` 和 `ready`；只有所有正式依赖都验收后才能报告 `ready`。

## Out of scope

- 开发、部署或管理 Blog 网站。
- 轮询、持续监控、定时执行、多主机采集或故障转移。
- 微信内的改稿、纠错、状态查询、发布指令或任务 ID 协议。
- 第一版多文章任务、粘贴链接、聊天记录包、独立图片/文件/小程序/视频卡片。
- 用 OCR 重建正文，保存动图，下载或转录音视频。
- 在同一投稿任务内维护改写修订历史。
- 自动删除、自动归档或云备份本地证据。
- 在没有真实运行证据时猜测重试次数、接口字段或图片托管方案。
