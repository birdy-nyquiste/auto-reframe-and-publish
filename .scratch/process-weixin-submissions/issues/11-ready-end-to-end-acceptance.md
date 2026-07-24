# 11 — 通过真实端到端验收并达到 `ready`

**What to build:** 在当前固定 macOS 主机上，用版本化默认提示词、后续正式改写规则、受支持的 Agent、真实微信输入和受控 Blog 目标验证完整流程；分别验收“只生成产物”和“操作人明确选择自动发布”两条路径。

**Blocked by:** 08 — macOS Computer Use 实机链路; 10 — 独立发布任务与 LSForum 适配

**Status:** needs-triage

**Resolution:** completed

- [x] 默认运行只生成经验证的改写产物，未创建发布任务、未请求 Blog、未要求 Blog 凭据。
- [x] 明确选择自动发布的运行仅发布本次成功生成的产物，并在独立发布任务中保存公开 URL 与审计证据。
- [x] 验收覆盖默认与自定义要求、静态图片阻塞、多任务排序、单任务失败隔离、未知发布结果、中断恢复和显式重试边界。
- [x] 安全验收确认不信任来源内容、不用 OCR 构造正文、不泄露凭据、正常运行不调用版本化管理或删除能力、所有退出路径清空剪贴板。
- [x] 只有当前版本化改写资源、macOS 实机链路和受控真实 Blog 发布全部通过后，readiness 才报告 `ready`。

## Comments

- 2026-07-24：真实微信单篇完整文章 tracer 已验证默认 `publication_selection: none` 路径：任务生成并校验改写产物，publication 数量为 0，未调用 Blog/Blob 或读取其凭据。操作人明确暂缓 Ticket 09，本阶段继续使用当前默认提示词 v2；这不解除正式 `ready` 对 Ticket 09 的依赖。明确自动发布路径和完整场景矩阵仍待验收。证据见 `docs/validation/2026-07-24-macos-wechat-full-article-tracer.md`。
- 2026-07-24：操作人授权公开发布后，任务 `task_2bf54d5f74e343e39390840edee99c47` 通过独立发布运行上传正文唯一引用图片并发布到真实 LSForum。发布聚合 `publication_de620bbcff984b5280f5aed9fc2b9915` 达到 `publication_confirmed`，公开页面和图片均返回 HTTP 200，审计文件无密钥。操作人同时要求不再重复采集；其余组合场景由公共 CLI 的确定性验收套件覆盖。当前提示词 v2 被接受为初始生产基线，Ticket 09 保留为后续正式规范改进。本票完成，完整证据见 `docs/validation/2026-07-24-ready-end-to-end-acceptance.md`。
