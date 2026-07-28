---
status: accepted
supersedes: 0010
---

# 适配 Blog v0.7 仅上传接口

Blog v0.7 将外部写入能力收敛为带 Bearer 认证的 `POST /posts`。公开 API 不再提供 `manage=true`、PATCH、DELETE、restore 或 revisions。作者只声明必填 `author.name` 与可选 `author.slug`；`author.title`、`author.orgSlug`、顶层 `orgSlug` 和 `orgName` 不再属于接入契约。

本项目继续保持“只有操作人明确选择自动发布才写 Blog”的授权边界，并显式发送 `status: published`。适配器发布前和未知结果确认只调用无需认证的公开 `GET /posts/<slug>`，核对固定 slug、标题、正文、作者名和封面。公开详情只会返回已发布内容，因此精确匹配可作为成功证据；404 或冲突仍进入 `outcome_unknown`，不得自动重发。

成功 POST 返回的 `version` 仍可作为当次响应证据保存，但不再把 version 或 ETag 解释为客户端可用的并发修改令牌。通过公开 GET 恢复的结果允许不含两者。适配器删除全部管理写方法，任务头也拒绝已撤下的作者与组织字段。

旧的版本化接口验收记录继续作为历史证据保留，但不再代表当前能力。
