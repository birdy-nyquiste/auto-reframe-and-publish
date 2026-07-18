# 12 — 适配版本化 Content API

**What to build:** 在不改变投稿采集与改写流程、也不扩大微信输入语法的前提下，更新 LSForum 适配器以支持显式发布状态、管理读取、乐观并发修改、软删除、恢复和只读历史；发布工作流继续只在操作人明确选择 `auto` 时创建公开文章。

**Blocked by:** 10 — 分离发布任务并适配 LSForum 即时发布

**Status:** ready-for-agent

**Resolution:** completed

- [x] `auto` 发布请求显式发送 `status: published`，不依赖服务端默认值。
- [x] 成功发布把服务端 `version` 与 HTTP `ETag` 保存到标准化发布结果。
- [x] 发布前检查和未知结果确认改用带 Bearer 认证的 `GET /posts/:slug?manage=true`，并校验文章仍为未删除的 `published` 状态。
- [x] 适配器提供显式的管理读取、PATCH、软删除、恢复与 revisions 方法；这些方法不进入微信字段、`run` 默认路径或自动恢复路径。
- [x] PATCH 只接受允许字段并严格发送 `If-Match: "<version>"`；HTTP 412 分类为 `blog_version_conflict`，不自动重试。
- [x] 所有新增接口从配置指定的运行时环境变量读取 Bearer key，不持久化密钥。
- [x] localhost HTTP 测试覆盖请求方法、路径、认证、状态、ETag、版本递增、412、软删除、恢复和历史读取。
- [x] ADR、Skill 边界、外部接口参考和验收说明同步更新。

## Comments

- 2026-07-17：根据 Blog 团队新增的版本化 Content API 说明完成适配。成功响应的完整 JSON Schema、各管理操作成功状态码和 ETag 的精确承载位置仍待对方正式 OpenAPI 确认；客户端当前同时以响应头为首选并兼容 JSON 中的 `etag`/`ETag`。
