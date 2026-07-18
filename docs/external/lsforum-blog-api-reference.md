# LSForum Blog 外部接口参考

> 状态：外部接口参考，不是正式契约。本文于 2026-07-17 根据 Blog 团队提供的 `api.md` 与 `ingestion.md` 整理。实现前仍应以对方确认的 OpenAPI、环境配置和变更通知为准。

## 用途

本文记录当前 LSForum Blog 已知的读取接口和即时发布接口，供本项目设计发布任务、实现适配器和排查联调问题时参考。

当前写入接口不是草稿接口。成功创建的内容会立即公开出现在首页 feed 和 `/posts/<slug>` 页面。

## 环境

| 项目 | 当前信息 |
| --- | --- |
| Base URL | `https://blog-lsforum.vercel.app/api/v1` |
| 正式/测试环境 | 只提供了一个当前地址，未确认独立测试环境 |
| 内容类型 | file-based post、import、API-ingested external post |
| 写入存储 | Postgres `ingested_posts` |
| 写入效果 | 立即公开，无需 rebuild |

## 认证

所有写请求使用：

```http
Authorization: Bearer <INGEST_API_KEY>
```

- 凭据由 Blog 项目的 `INGEST_API_KEY` 环境变量配置。
- 调用方应从运行时环境变量或凭据存储读取，不得写入请求 JSON、浏览器代码、Git、任务记录或报告。
- 缺少或空白的服务端 key 配置返回 `503`。
- 调用方提供错误 key 返回 `401`。
- 当前材料没有定义 scope；同一个 key 同时具备即时发布和删除 API-ingested post 的权限。

## Endpoint 概览

| Method | Path | Auth | 当前语义 |
| --- | --- | --- | --- |
| `GET` | `/posts` | 无 | 合并读取 published post、import 和 external post |
| `GET` | `/posts/:slug` | 无 | 读取公开 post 详情 |
| `GET` | `/posts/:slug?format=markdown` | 无 | 读取英文 Markdown 正文 |
| `POST` | `/posts` | Bearer | 创建并立即公开一篇 external post |
| `DELETE` | `/posts/:slug` | Bearer | 删除 API-ingested post |
| `GET` | `/imports/:keyword` | 无 | 读取 import/repost 详情 |
| `GET` | `/orgs` | 无 | 读取组织列表 |
| `GET` | `/orgs/:slug` | 无 | 读取组织详情 |
| `GET` | `/openapi.json` | 无 | 对方声明的 OpenAPI 3.0 文档地址 |

本项目的发布适配器只允许使用必要的 `POST` 和用于确认结果的 `GET`。即使凭据允许，也不实现 `DELETE`。

## 创建并公开文章

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
| `authorName` | string | 是 | 自由文本；也接受别名 `author` |
| `excerpt` | string | 否 | 最多 500 字符；省略时从正文生成 |
| `slug` | string | 否 | 省略时从标题生成；冲突时自动去重 |
| `postType` | `article` 或 `opinion` | 否 | 默认 `article` |
| `category` | string | 否 | 默认 `General` |
| `titleZh` | string | 否 | 中文标题 |
| `excerptZh` | string | 否 | 中文摘要 |
| `contentZh` | string | 否 | 中文 Markdown 正文 |
| `authorTitle` | string | 否 | 作者头衔自由文本 |
| `orgName` | string | 否 | 组织或来源自由文本标签 |
| `image` | http(s) URL | 否 | 卡片和 hero 封面图 |
| `sourceUrl` | http(s) URL | 否 | 原始来源地址 |
| `readTime` | string | 否 | 省略时自动估算 |
| `featured` | boolean | 否 | 默认 `false` |
| `tags` | string[] 或逗号分隔 string | 否 | 最多 12 个 SEO 标签 |

### 最小示例

```json
{
  "title": "How users are adopting AI agents",
  "authorName": "Jane Doe",
  "content": "# Heading\n\nMarkdown body goes here."
}
```

### Success

HTTP `201`：

```json
{
  "ok": true,
  "slug": "how-users-are-adopting-ai-agents",
  "url": "https://blog-lsforum.vercel.app/posts/how-users-are-adopting-ai-agents",
  "item": {
    "kind": "external",
    "slug": "how-users-are-adopting-ai-agents"
  }
}
```

`slug` 与 `url` 指向已经公开的文章，不是草稿 ID或后台预览地址。

### 已知错误

| HTTP | 当前说明 |
| --- | --- |
| `400` | 请求字段缺失或无效；message 应指出问题 |
| `401` | Bearer key 错误 |
| `404` | 读取未知 slug、keyword、org，或访问未公开内容 |
| `405` | 当前对 post 使用 `PATCH` 或 `PUT` |
| `503` | 服务端未配置 key 或数据库 |

当前材料没有完整定义 `403`、`409`、`413`、`415`、`422`、`429`、5xx、字段级错误结构、追踪 ID及 `Retry-After`。

## 读取和归属语义

- API 创建的文章以 `kind: external` 合并到公共 feed。
- 公开详情由 `GET /posts/:slug` 返回；`?format=markdown` 返回正文。
- external post 显示 Community badge。
- external post 不关联 member organization，也不会出现在 `/orgs/:slug` 的内容列表中。
- `authorName` 和 `orgName` 都是自由文本，不是稳定的作者或组织资源 ID。
- SEO 由 Blog 根据 title、excerpt、image、authorName、orgName、date 和 tags 自动生成。

## 编辑和删除

- 当前不支持编辑；`PATCH` 和 `PUT` 返回 `405`。
- 对方文档给出的临时编辑方案是删除后使用相同显式 slug 重建。
- 该方案非原子，会重置发布日期，本项目不采用。
- 本项目不通过适配器调用 `DELETE`。

## UAT 限制

对方当前建议的 UAT 是发布标题带 `[UAT TEST]` 的公开文章，读取验证后再调用 DELETE 清理。本项目不采用这一流程：测试期间内容会短暂公开，而且我们的适配器刻意不具备删除能力。

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
2. 发送前查询固定 slug，防止已知的重复发布。
3. 收到 `201` 后持久化原始及规范化响应。
4. 超时或连接中断后查询固定 slug，并校验可观察字段。
5. 仍无法确认时进入 `outcome_unknown`，不得自动再次 POST。
6. 只有确认目标 slug 不存在后，操作人才可以显式允许重试。

这些客户端措施只能降低风险，不能提供服务端 exactly-once 保证。服务端自动修改冲突 slug 时，响应丢失后的恢复仍可能无法确定。

## 项目计划采用方式

以下是 ADR-0009 已确定并由当前适配器实现的设计：

- 内容处理与公开发布是两个不同的任务生命周期。
- 投稿任务产生不可变改写产物，不因 Blog 字段变化而重做采集和来源重建。
- 发布任务读取改写产物并负责 Blog 字段映射、图片 URL、请求、响应和未知结果处理。
- `run` 只有在操作人本次明确选择自动发布时才创建并执行发布任务。
- 未提及发布或明确选择不发布时，`run` 停在改写产物完成，不调用外部写接口。
- 来源文章、微信任务头和 Blog 响应都不能自行打开自动发布。

2026-07-17 已完成一次经操作人明确授权的纯文本 UAT 公开发布与独立 GET 回读，证据见 [LSForum 真实接口验收](../validation/2026-07-17-lsforum-live-acceptance.md)。该验收不覆盖图片、正式改写或 Windows 微信采集。

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

## 来源记录

- Blog 团队 `api.md`：总体读取和写入接口、公共内容结构、组织及字段字典。
- Blog 团队 `ingestion.md`：部署地址、认证、即时发布流程、UAT、编辑限制及无幂等警告。

两份原始文件位于项目仓库之外，没有作为正式 vendor snapshot 提交。若对方文档更新，应重新核对本参考，而不是假设其自动同步。
