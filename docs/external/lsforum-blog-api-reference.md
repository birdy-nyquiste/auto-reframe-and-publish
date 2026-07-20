# LSForum Blog 外部接口参考

> 状态：外部接口参考，不是本项目拥有的契约。本文于 2026-07-17 根据 Blog 团队材料整理，并由部署中的 OpenAPI v1.2.0 与真实 draft 生命周期 UAT 校正。实现仍应以部署 OpenAPI、环境配置和变更通知为准。

## 用途

本文记录当前 LSForum Blog 已知的读取、创建和版本化管理接口，供本项目设计发布任务、实现适配器和排查联调问题时参考。

创建接口现在支持 `draft | published`。服务端默认 `published`；本项目的 `auto` 发布路径显式发送 `published`，不依赖默认值。草稿和软删除内容只能通过带认证的管理读取获取。

## 环境

| 项目 | 当前信息 |
| --- | --- |
| Base URL | `https://blog-lsforum.vercel.app/api/v1` |
| 部署 OpenAPI | `1.2.0`（2026-07-17 实际读取） |
| 正式/测试环境 | 只提供了一个当前地址，未确认独立测试环境 |
| 内容类型 | file-based post、import、API-ingested external post |
| 写入存储 | Postgres `ingested_posts` |
| 写入效果 | `published` 立即公开且无需 rebuild；`draft` 不公开 |

## 认证

创建和全部管理接口统一使用：

```http
Authorization: Bearer <INGEST_API_KEY>
```

- 凭据由 Blog 项目的 `INGEST_API_KEY` 环境变量配置。
- 调用方应从运行时环境变量或凭据存储读取，不得写入请求 JSON、浏览器代码、Git、任务记录或报告。
- 缺少或空白的服务端 key 配置返回 `503`。
- 调用方提供错误 key 返回 `401`。
- 当前材料没有定义 scope；同一个 key 可创建、读取受限状态、修改、软删除、恢复及查看历史。

## Endpoint 概览

| Method | Path | Auth | 当前语义 |
| --- | --- | --- | --- |
| `GET` | `/posts` | 无 | 合并读取 published post、import 和 external post |
| `GET` | `/posts/:slug` | 无 | 读取公开 post 详情 |
| `GET` | `/posts/:slug?format=markdown` | 无 | 读取英文 Markdown 正文 |
| `POST` | `/posts` | Bearer | 创建 `draft` 或 `published` external post；默认 published |
| `GET` | `/posts/:slug?manage=true` | Bearer | 读取草稿、软删除状态及当前 version |
| `PATCH` | `/posts/:slug` | Bearer + `X-Post-Version` | 按当前 version 局部修改；成功后 version 增加 |
| `DELETE` | `/posts/:slug` | Bearer | 软删除文章，使其不再公开显示 |
| `POST` | `/posts/:slug/restore` | Bearer | 恢复软删除文章 |
| `GET` | `/posts/:slug/revisions` | Bearer | 读取只读操作历史和版本快照 |
| `GET` | `/imports/:keyword` | 无 | 读取 import/repost 详情 |
| `GET` | `/orgs` | 无 | 读取组织列表 |
| `GET` | `/orgs/:slug` | 无 | 读取组织详情 |
| `GET` | `/openapi.json` | 无 | 对方声明的 OpenAPI 3.0 文档地址 |

本项目正常 `run` 只允许使用显式 published `POST` 和用于确认结果的管理 `GET`。适配器具有窄的管理方法以匹配接口，但它们不是微信输入、CLI operation、正常运行步骤或自动恢复动作；彻底删除与历史修改不实现。

## 创建文章

```http
POST /api/v1/posts
Content-Type: application/json
Authorization: Bearer <INGEST_API_KEY>
```

### Request body

| Field | Type | Required | 当前说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 最多 200 字符 |
| `content` | string | 是 | Markdown；raw HTML 不渲染 |
| `author` | object | 否 | 首选作者身份；name 必填，可含 externalId、slug、title、orgSlug |
| `authorName` | string | 否 | 旧版自由文本作者名 |
| `authorExternalId` | string | 否 | 调用方稳定作者 ID |
| `authorSlug` | string | 否 | 公开作者 slug |
| `excerpt` | string | 否 | 最多 500 字符；省略时从正文生成 |
| `slug` | string | 否 | 省略时从标题生成；冲突时自动去重 |
| `postType` | `article` 或 `opinion` | 否 | 默认 `article` |
| `category` | string | 否 | 默认 `General` |
| `titleZh` | string | 否 | 中文标题 |
| `excerptZh` | string | 否 | 中文摘要 |
| `contentZh` | string | 否 | 中文 Markdown 正文 |
| `authorTitle` | string | 否 | 作者头衔自由文本 |
| `orgName` | string | 否 | 组织或来源自由文本标签 |
| `orgSlug` | string | 否 | 已存在组织的 slug |
| `image` | http(s) URL | 否 | 卡片和 hero 封面图 |
| `sourceUrl` | http(s) URL | 否 | 原始来源地址 |
| `readTime` | string | 否 | 省略时自动估算 |
| `featured` | boolean | 否 | 默认 `false` |
| `tags` | string[] 或逗号分隔 string | 否 | 最多 12 个 SEO 标签 |
| `status` | `draft` 或 `published` | 否 | 默认 `published`；本项目自动发布时显式发送 `published` |

### 最小示例

```json
{
  "title": "How users are adopting AI agents",
  "authorName": "Jane Doe",
  "content": "# Heading\n\nMarkdown body goes here.",
  "status": "published"
}
```

### Success

HTTP `201`。真实 UAT 确认 JSON 返回正整数 `version`，HTTP 响应头返回带双引号的 ETag；客户端以响应头为首选，并兼容 JSON 中的 `etag` 或 `ETag`：

```http
ETag: "1"
```

```json
{
  "ok": true,
  "slug": "how-users-are-adopting-ai-agents",
  "url": "https://blog-lsforum.vercel.app/posts/how-users-are-adopting-ai-agents",
  "item": {
    "kind": "external",
    "slug": "how-users-are-adopting-ai-agents"
  },
  "version": 1
}
```

`published` 时 `slug` 与 `url` 指向公开文章；`draft` 响应也返回相同 URL，但公共 GET 为 `404`，不能把该 URL 当作公开成功证据。

### 已知错误

| HTTP | 当前说明 |
| --- | --- |
| `400` | 请求字段缺失或无效；message 应指出问题 |
| `401` | Bearer key 错误 |
| `404` | 读取未知 slug、keyword、org，或访问未公开内容 |
| `412` | PATCH 的 `X-Post-Version` 已过期；响应提供当前 version |
| `428` | PATCH 缺少或提供了非法的 `X-Post-Version` |
| `503` | 服务端未配置 key 或数据库 |

当前材料没有完整定义 `403`、`409`、`413`、`415`、`422`、`429`、5xx、字段级校验 details、追踪 ID 及 `Retry-After`。

## 读取和归属语义

- API 创建的文章以 `kind: external` 合并到公共 feed。
- 公开详情由 `GET /posts/:slug` 返回；`?format=markdown` 返回正文。
- 草稿、软删除文章和当前 version 由带 Bearer 认证的 `GET /posts/:slug?manage=true` 返回。
- external post 显示 Community badge。
- external post 不关联 member organization，也不会出现在 `/orgs/:slug` 的内容列表中。
- `authorName` 和 `orgName` 都是自由文本，不是稳定的作者或组织资源 ID。
- SEO 由 Blog 根据 title、excerpt、image、authorName、orgName、date 和 tags 自动生成。

## 版本化编辑、软删除和历史

- `PATCH /posts/:slug` 支持局部修改，必须发送 `X-Post-Version: "<当前version>"`。同事消息曾写成 `If-Match`，但部署 OpenAPI 与真实 UAT 均确认实际头名为 `X-Post-Version`。
- 成功修改后 version 自动增加；版本过期返回 `412`。调用方必须重新读取并由操作人决定如何处理冲突，不能静默覆盖或自动重试。
- `DELETE /posts/:slug` 是软删除：文章不再公开显示，但记录仍存在并可恢复。
- `POST /posts/:slug/restore` 恢复软删除文章。
- `GET /posts/:slug/revisions` 返回 `{slug, items}`，items 按最新版本优先，action 为 `create | update | delete | restore` 并包含只读 snapshot。历史不能通过 API 修改或彻底删除。
- 彻底删除只能由网站管理员在数据库后台处理，本项目不提供该能力。
- OpenAPI 的 PATCH 字段白名单不包含 slug，允许内容、作者身份、组织、展示字段和 `draft | published | archived` 生命周期状态；适配器使用同一白名单。
- 管理读取使用 `deletedAt` 表示软删除状态：活动记录为 `null`，软删除记录为时间戳。适配器仍兼容 `deleted` / `isDeleted` 布尔表示，但字段完全缺失时保守地视为结果未知。
- 管理错误采用 `{error: {code, message, ...}}`；适配器同时兼容早期顶层 `message`。

## UAT 限制

早期材料建议发布标题带 `[UAT TEST]` 的公开文章，读取验证后再删除。现在 DELETE 是软删除，不等于清除测试数据；真实联调仍必须使用操作人批准的内容和目标，测试后的软删除或管理员彻底清理由双方另行约定。

真实联调前需要由 Blog 团队提供可接受公开测试内容的安全目标和清理负责人，或者提供隔离的 staging 环境。测试发布也必须由操作人明确授权。

## 图片能力

当前接口只定义一个公开 http(s) `image` URL，语义是卡片和 hero 封面图。材料没有提供：

- 图片上传 endpoint；
- 正文多图资源模型；
- 本地图片转公开 URL 的流程；
- 图片类型、大小、数量或总请求限制；
- 远程图片抓取、缓存和失败语义。

因此，包含本地图片的发布任务必须先获得稳定公开 URL。图片托管能力未配置时，不得静默丢弃图片后发布。

## 幂等、重试和未知结果

当前接口不支持 idempotency key。对方明确建议暂时避免自动重试，因为重复 POST 可能创建重复公开文章。

本项目适配时采用以下保守规则：

1. 发布前持久化 publication ID、固定显式 slug、rewrite commit hash 和完整请求。
2. 发送前用带认证的 `manage=true` 查询固定 slug，防止草稿或软删除记录导致重复/冲突。
3. 收到 `201` 后持久化原始及规范化响应。
4. 超时或连接中断后管理查询固定 slug，并校验标题、正文、作者、published 状态及未删除状态。
5. 仍无法确认时进入 `outcome_unknown`，不得自动再次 POST。
6. 只有确认目标 slug 不存在后，操作人才可以显式允许重试。

这些客户端措施只能降低风险，不能提供服务端 exactly-once 保证。服务端自动修改冲突 slug 时，响应丢失后的恢复仍可能无法确定。

## 项目计划采用方式

以下是 ADR-0009 已确定并由当前适配器实现的设计：

- 内容处理与公开发布是两个不同的任务生命周期。
- 投稿任务产生不可变改写产物，不因 Blog 字段变化而重做采集和来源重建。
- 发布任务读取改写产物并负责 Blog 字段映射、图片 URL、请求、响应和未知结果处理。
- `auto` 明确提交 `status: published`，并在成功结果中保留 version 与 ETag。
- 发布确认使用带认证的管理 GET；适配器管理方法不由普通 `run` 自动调用。
- `run` 只有在操作人本次明确选择自动发布时才创建并执行发布任务。
- 未提及发布或明确选择不发布时，`run` 停在改写产物完成，不调用外部写接口。
- 来源文章、微信任务头和 Blog 响应都不能自行打开自动发布。

2026-07-17 已完成一次经操作人明确授权的纯文本 UAT 公开发布与独立 GET 回读，证据见 [LSForum 真实接口验收](../validation/2026-07-17-lsforum-live-acceptance.md)。该验收不覆盖图片、正式改写或 macOS 微信采集。

同日还完成版本化 Content API 的真实 draft 生命周期验收，覆盖创建、管理读取、成功 PATCH、过期版本 412、软删除、恢复、revisions、公共隐藏和最终软删除，证据见 [版本化 Content API 真实验收](../validation/2026-07-17-versioned-content-api-live-acceptance.md)。

## 尚未确认

- 当前 Base URL 是否为长期生产地址；是否有独立 staging/UAT 环境。
- `/openapi.json` 是否与部署版本严格同步及其版本策略。
- slug 的字符和长度限制，以及显式 slug 冲突时的精确算法。
- 未知 JSON 字段是拒绝还是忽略。
- `author` 与 `authorName` 同时出现时的优先级。
- `tags` 两种输入形态的规范化规则。
- 正文大小、请求体大小、速率和并发限制。
- 成功写入与公共读取之间是否存在延迟。
- 远程 image URL 是否由 Blog 下载、代理或永久外链。
- key 的轮换、撤销、scope 和目标隔离能力。
- ETag 是否也可能在 JSON 中返回，以及 revisions 是否会增加分页或保留期限。
- 版本 header 为何偏离同事消息中的 `If-Match`，以及未来是否会再次迁移到标准条件请求头。
- PATCH 各 nullable 字段的清空细节，以及 draft/published/archived 之间的业务约束。

## 来源记录

- Blog 团队 `api.md`：总体读取和写入接口、公共内容结构、组织及字段字典。
- Blog 团队 `ingestion.md`：部署地址、认证、即时发布流程、UAT、早期编辑限制及无幂等警告。
- Blog 团队 2026-07-17 Content API 更新说明：status、manage 读取、条件 PATCH、软删除、恢复、revisions 与统一认证。
- 部署中的 `/api/v1/openapi.json` v1.2.0：当前路径、header、字段、成功/错误 Schema。
- 2026-07-17 真实 draft 生命周期 UAT：确认部署行为及版本递增、ETag、公共隐藏和 revisions 快照。

两份原始文件位于项目仓库之外，没有作为正式 vendor snapshot 提交。若对方文档更新，应重新核对本参考，而不是假设其自动同步。
