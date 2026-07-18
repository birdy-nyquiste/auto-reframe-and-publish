# 10 — 分离发布任务并适配 LSForum 即时发布

**What to build:** 保持投稿采集与改写流程不变，把公开发布建模为独立、可审计的发布任务；`run` 默认不发布，只有操作人在本次运行中明确选择 `auto` 才对本次成功生成的改写产物创建并执行发布任务。发布适配器按仓库内的 LSForum 外部接口参考实现，不把 Blog 字段或状态写回投稿任务。

**Blocked by:** 07 — 核心多任务运行

**Status:** ready-for-agent

**Resolution:** completed

- [x] 投稿任务在 `rewrite_artifact_ready` 结束，不包含发布模式、外部文章 ID、URL 或发布里程碑；已提交的改写产物仍是发布请求唯一内容来源。
- [x] `run` 接受可信的运行级发布选择 `none | auto`，省略时等同 `none`；`none` 不创建发布任务、不调用 Blog、不要求 Blog 凭据。
- [x] `auto` 只为本次运行中成功到达 `rewrite_artifact_ready` 的投稿任务创建发布任务；历史产物不会被一次普通运行意外批量公开。
- [x] 发布任务是与 run、投稿任务同级的持久化聚合，引用投稿任务 ID 与改写 commit，独立记录状态、阻塞原因、请求、尝试、原始响应和标准化结果。
- [x] 每个发布任务在发送前固定并持久化 slug 与完整请求。目标 ID 通过非敏感配置映射到 LSForum `authorName` 及允许的附加投稿字段；外部接口当前没有稳定 author ID，映射缺失时在本地阻塞且不发送。
- [x] 初版真实适配器只把 `POST /api/posts` 与按 slug GET 接入运行工作流，API key 只从运行时环境取得；后续 Content API 管理能力由 Ticket 12 和 ADR-0010 以受限方法适配，仍不进入普通运行。
- [x] 包含本地图片但没有稳定公网图片 URL 的改写产物阻塞发布，不静默丢图、不上传到未约定的服务。
- [x] POST 明确成功时持久化公开 URL 和响应；明确拒绝时记录失败；超时或连接中断导致结果未知时先按 slug 查询，仍无法确认则进入 `outcome_unknown`，不得自动再次 POST。
- [x] 单个发布失败不回滚改写产物，也不中断同一运行中的其他投稿或发布任务。
- [x] CLI 端到端测试覆盖默认不发布、显式不发布、显式自动发布、目标映射缺失、图片阻塞、公开成功、明确拒绝和未知结果；HTTP 测试使用本地 fixture，不调用生产服务。
- [x] 状态与运行报告分别汇总投稿和发布结果；在 Windows Computer Use、正式改写规则和受控真实接口验收完成前，readiness 仍不得报告 `ready`。

## Comments

- 2026-07-17：完成 LSForum 适配器、本地 HTTP fixtures、受控真实 POST/GET 验收，以及联调发现的密钥格式和悬空发布恢复加固。真实验收证据见 `docs/validation/2026-07-17-lsforum-live-acceptance.md`。
