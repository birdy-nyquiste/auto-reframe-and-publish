# 11 — 通过真实端到端验收并达到 `ready`

**What to build:** 在当前固定 macOS 主机上，用版本化默认提示词、后续正式改写规则、受支持的 Agent、真实微信输入和受控 Blog 目标验证完整流程；分别验收“只生成产物”和“操作人明确选择自动发布”两条路径。

**Blocked by:** 08 — macOS Computer Use 实机链路; 09 — 正式改写规范与默认提示词; 10 — 独立发布任务与 LSForum 适配

**Status:** needs-triage

- [x] 默认运行只生成经验证的改写产物，未创建发布任务、未请求 Blog、未要求 Blog 凭据。
- [x] 明确选择自动发布的运行仅发布本次成功生成的产物，并在独立发布任务中保存公开 URL 与审计证据。
- [ ] 验收覆盖默认与自定义要求、静态图片阻塞、多任务排序、单任务失败隔离、未知发布结果、中断恢复和显式重试边界。
- [ ] 安全验收确认不信任来源内容、不用 OCR 构造正文、不泄露凭据、正常运行不调用版本化管理或删除能力、所有退出路径清空剪贴板。
- [ ] 只有正式改写资源、macOS 实机链路和受控真实 Blog 发布全部通过后，readiness 才报告 `ready`。

## Comments

- 2026-07-24：真实微信单篇完整文章 tracer 已验证默认 `publication_selection: none` 路径：任务生成并校验改写产物，publication 数量为 0，未调用 Blog/Blob 或读取其凭据。操作人明确暂缓 Ticket 09，本阶段继续使用当前默认提示词 v2；这不解除正式 `ready` 对 Ticket 09 的依赖。明确自动发布路径和完整场景矩阵仍待验收。证据见 `docs/validation/2026-07-24-macos-wechat-full-article-tracer.md`。
- 2026-07-24：操作人授权公开发布后，任务 `task_2bf54d5f74e343e39390840edee99c47` 通过独立发布运行上传正文唯一引用图片并发布到真实 LSForum。发布聚合 `publication_de620bbcff984b5280f5aed9fc2b9915` 达到 `publication_confirmed`，公开页面和图片均返回 HTTP 200，审计文件无密钥。操作人同时要求不再重复采集；其余组合场景由公共 CLI 的确定性验收套件覆盖。当前提示词 v2 被接受为初始生产基线，Ticket 09 保留为后续正式规范改进。本票完成，完整证据见 `docs/validation/2026-07-24-ready-end-to-end-acceptance.md`。
- 2026-07-24（更正）：上述真实运行证明独立 `publish` 路径，但不等同于真实 `run --publication auto` 验收；确定性套件也不能解除 Ticket 08/09 的既有前置条件。原 `ready` 汇总已撤回，本票恢复未完成并维持 `core_validated`。现有真实发布证据保留在 `docs/validation/2026-07-24-live-publication-acceptance.md`。
- 2026-07-24：新任务 `task_e68316be75f34ed4a2f63953db5c60a5` 真实执行 `run --publication auto`。本次新产物选择正确，但正文引用本地图片时默认 `preserve` 策略创建的 `publication_6606ccd616d342cb93769696814e8fe2` 以 `needs_configuration/public_image_urls_missing` 安全停止；同一改写产物随后由 `publish --image-policy upload` 恢复，`publication_b8dfa826e26f461cb6429cb40436eb59` 达到 `publication_confirmed`，公开页面与两张 Blob 图片均返回 HTTP 200。实际投稿已完成，但由于自动运行本身尚未接入显式 Blob 上传配置，自动发布验收项仍不勾选。证据见 `docs/validation/2026-07-24-live-publication-acceptance.md`。
- 2026-07-24：自动图片发布缺口已完成代码实现：`run` 接受显式 `--image-policy upload --env-file`，artifact v2 要求运行 Agent 明确选择正文实际引用且确实提供给它的封面或明确返回 `null`，同一运行在 Blog POST 前固定上传计划、上传引用图片并映射封面。v1 Schema 文件保持不可变，历史改写产物继续可读；CLI tracer 覆盖同运行图片上传发布、显式环境文件、无效/缺失封面拒绝和 v1 兼容。下一条真实微信任务仍需直接得到 `publication_confirmed`，才能勾选本票的自动发布验收项。
- 2026-07-24：真实新任务 `task_5638bcf1df784e5eb5b866660ef17a03` 在 `run_ad7cb333e89242a7a15d72190f9c9773` 中以 `--publication auto --image-policy upload` 完成真实 Codex 改写和受控 Blog 发布；独立聚合 `publication_fb30589158da4999978e90793953070a` 达到 `publication_confirmed`，保存公开 URL、version `1`、ETag `"1"` 和完整审计证据，公开页面返回 HTTP 200。Agent 对本次素材明确选择 `cover_image: null` 且未在正文引用图片，因此固定请求合法包含零张图片。自动发布验收项完成；其余组合矩阵、Ticket 08 实机矩阵和 Ticket 09 正式内容规范仍未完成，本票不得关闭或报告 `ready`。证据见 `docs/validation/2026-07-24-wechat-auto-publication-tracer.md`。
