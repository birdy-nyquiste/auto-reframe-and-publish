# 13 — 适配 LSForum API v0.6 作者与呈现默认值

**What to build:** 保持投稿和图片处理流程不变，将 LSForum 发布映射更新为 v0.6：新目标按 `author.name` 归并作者，不再依赖被忽略的 external ID；明确当前目标的 `postType`，并保留 excerpt 缺省时不生成引言的语义。

**Blocked by:** 12 — 适配版本化 Content API

**Status:** ready-for-agent

**Resolution:** completed

- [x] 新目标的嵌套 `author` 只要求 `name`，并允许可选 `slug`、`title`、`orgSlug`。
- [x] 作者名作为身份键时拒绝首尾空白与控制字符，避免视觉相同但实际分裂的作者记录。
- [x] 新目标映射与 PATCH 拒绝无效的 `externalId` / `authorExternalId`，防止调用方误认为它仍控制作者身份。
- [x] 历史 v0.5 固定发布请求在发送时剔除旧 external ID，以保留安全恢复能力而不向 v0.6 发送无效字段。
- [x] 当前 `birdy-test` 目标显式映射为 `postType: opinion`，且发布路径不生成或发送 `excerpt`。
- [x] Skill 发布参考、领域词汇和外部接口参考同步到 v0.6，并记录部署 OpenAPI 仍为 1.4.0。
- [x] localhost 合约测试覆盖 name-based 作者、旧请求兼容、无效作者 ID 拒绝、缺省 excerpt 与显式 postType。
