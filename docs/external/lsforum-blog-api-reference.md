# LSForum Blog API（内部文档）

> 合作方对接与运维说明。实现与此文档及 `/api/v1/openapi.json` 保持一致。
> 原 `ingestion.md` 已合并入本文档。

**API version: v0.7**

| 版本 | 能力 |
| ---- | ---- |
| v0.3 | 封面 `image` 外链 → Public Vercel Blob |
| v0.4 | 正文 `content` / `contentZh` 内 `![](url)` 外链 → Blob |
| v0.5 | 文档与实现对齐：Public Blob 要求、OIDC 认证、临时 URL 语义、完整 UAT |
| v0.6 | `excerpt` 无默认值；`postType` 默认 `opinion`；作者按 `author.name` 匹配 |
| v0.7 | 写入仅上传（无 PATCH/DELETE）；去掉 `author.title` / `orgSlug` 声明；时间戳与阅读时间约定固化 |

---

## Base URL

| 环境 | Base URL | 说明 |
| ---- | -------- | ---- |
| **当前可用（推荐联调）** | `https://blog-lsforum.vercel.app/api/v1` | Vercel 默认域名 |
| 生产（待 DNS） | `https://blog.lsforum.org/api/v1` | 需先将 `blog.lsforum.org` 解析到 Vercel |

下文示例默认使用 **blog-lsforum.vercel.app**。绑定自定义域名后替换即可。

Base path: `/api/v1`
公开读接口无需认证。**写入仅支持上传**：`POST /api/v1/posts`，使用 `Authorization: Bearer <INGEST_API_KEY>`。无公开更新/删除接口。
响应默认 `Content-Type: application/json; charset=utf-8`；`?format=markdown` 返回纯 Markdown。

标量字段缺省为 `null`；数组缺省为 `[]`。公开接口仅返回 `status = "published"` 的内容。

Feed 三种 `kind`：`post`（git 文件）、`import`（Industry News）、`external`（API 推送）。

Machine-readable schema: [`/api/v1/openapi.json`](/api/v1/openapi.json)

---

## 一次性配置（LSForum 运维）

### 1. Postgres

Vercel → Storage → Postgres/Neon。自动注入 `POSTGRES_URL`（或自行设置 `DATABASE_URL`）。
首次 API 调用自动建表。

### 2. Blob — 必须 Public Store

> **P0：必须创建 Public Blob Store。Private Store 不能用于公开文章图片。**

若在 Private Store 上调用 `put({ access: 'public' })`，会报错：
`Cannot use public access on a private store`。

| 步骤 | 操作 |
| ---- | ---- |
| 创建 | Storage → Create → **Blob** → Access: **Public**（不要选 Private） |
| 连接 | 勾选 **blog-lsforum** 项目及 Production / Preview / Development |
| 验证 | 环境变量中出现 Blob 相关项；部署后 ingest 返回的 URL 含 **`.public.blob.vercel-storage.com`** |

**认证（二选一，代码均已兼容）：**

| 方式 | 环境变量 | 说明 |
| ---- | -------- | ---- |
| **OIDC（Vercel 默认）** | `BLOB_STORE_ID` + `VERCEL_OIDC_TOKEN` | 部署在 Vercel 时自动注入/轮换 |
| **静态 Token（本地/CI）** | `BLOB_READ_WRITE_TOKEN` | `vercel env pull .env.local` 获取 |

本地开发：`vercel env pull .env.local`，确保上述变量之一可用。

### 3. INGEST_API_KEY

```bash
openssl rand -hex 32
```

写入 Vercel 环境变量，通过密码管理器单独发给合作方。**勿写入仓库、勿放前端。**

### 4. 重新部署

修改 Storage 或环境变量后必须 Redeploy。

未配置 Postgres 或 API Key → 写入返回 `503`；站点仍可按 git 文件内容运行。

---

## 认证

```http
Authorization: Bearer <INGEST_API_KEY>
```

仅合作方**服务端**调用；浏览器/移动端不得持有该密钥。

---

## 合作方快速上手

### 最小发布

```bash
curl -X POST https://blog-lsforum.vercel.app/api/v1/posts \
  -H "Authorization: Bearer $INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test opinion",
    "author": { "name": "Jane Doe" },
    "content": "# Hello\n\nBody text.",
    "image": "https://example.com/cover.jpg"
  }'
```

成功 `201`：保存 `slug`、`url`。打开 `url` 验证页面；`GET /api/v1/posts/<slug>` 核对 `content` 与 `image`。

### 作者（`author`）

| 字段 | 必填 | 说明 |
| ---- | ---- | ---- |
| `author.name` | ✅ | 作者显示名；**同一 `name` 视为同一作者**（跨稿件合并） |
| `author.slug` | | 可选；缺省由 `name` 生成 URL slug |

不声明 `author.title` / `author.orgSlug`（易与文章 `title` 混淆）；请勿依赖。

不再使用 `externalId` / `authorExternalId` 判别作者；传入也会被忽略。

### `postType`：`article` 与 `opinion`

| 值 | 默认 | 适用内容 |
| ---- | ---- | -------- |
| `opinion` | **是** | 成员代表个人观点，不代表 LSForum 官方立场；出现在 `/opinion` |
| `article` | 否 | 组织正式稿件；需显式传 `"postType": "article"` |

`category` 是主题标签（如 `AI`），与 `postType` 无关。

### `excerpt`（引言）

| 规则 | 说明 |
| ---- | ---- |
| 可选 | 不传、传 `null` 或空字符串 → **不生成、不展示**引言块 |
| 有值 | 详情页标题下显示为引用块；≤ 500 字 |
| 禁止依赖缺省 | **不会**从 `content` 自动截取（避免露出 `![](url)` 等 Markdown） |

需要引言时显式传纯文本摘要，例如：`"excerpt": "复联4重映传闻与下一部的叙事衔接。"`

### 时间戳与阅读时间

| 概念 | 字段 | 规则 |
| ---- | ---- | ---- |
| **Published At** | `publishedAt`（管理响应）/ 列表 `date` | 服务端在首次 `published` 时自动写入；外部**不可自定义** |
| 前台展示 | `date` | 只显示到**日**（如 `July 27, 2026`） |
| **Read time** | `readTime` | 可选；不传则按英文正文约 220 wpm 估算为 `"N min read"`，**始终展示** |

Created At / Updated At 仅出现在上传响应的 `item` 中，前台不单独展示。

### 上传（唯一写入能力）

| 动作 | 方法 | 要点 |
| ---- | ---- | ---- |
| 上传 | `POST /api/v1/posts` | Bearer `INGEST_API_KEY` |

无 `PATCH` / `DELETE` / `restore` / `revisions` / `?manage=true`。

---

## 图片：两种标准工作流

API **不接受** `multipart` 上传、Base64、`data:` URL。仅接受 JSON 中的 URL 字符串。

### 工作流 A — 合作方已有公开临时 URL（推荐）

1. `POST` 时在 `image` 和/或 `content` 里填入 `https://…`
2. 服务端拉取并写入 **Public Blob**
3. 响应与数据库存 **`.public.blob.vercel-storage.com`** URL

### 工作流 B — 编辑只有本地文件

1. 先上传到 Public Blob（需已 `vercel link` 且 env 已 pull）：

```bash
vercel blob put ./cover.jpg --pathname covers/manual/cover.jpg
# 返回 https://….public.blob.vercel-storage.com/…
```

2. 将返回 URL 填入 JSON 的 `image` 或 Markdown `![](url)`
3. 再 `POST /api/v1/posts`（已托管 URL 不会重复上传）

大量正文图（>5 张）建议**先全部 `vercel blob put`，再提交已托管 URL**，避免单次 Serverless 请求超时。

---

## Endpoints

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| GET | `/api/v1/posts` | — | 已发布合并 feed |
| GET | `/api/v1/posts/:slug` | — | 文章详情 |
| GET | `/api/v1/posts/:slug?format=markdown` | — | 英文 Markdown 正文 |
| POST | `/api/v1/posts` | Ingest key | **上传（创建）** |
| GET | `/api/v1/imports/:keyword` | — | Industry News 详情 |
| GET | `/api/v1/orgs` | — | 组织列表 |
| GET | `/api/v1/orgs/:slug` | — | 组织详情 |
| GET | `/api/v1/openapi.json` | — | OpenAPI 3.0 |

---

## POST `/api/v1/posts`

### Request body

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `title` | string | ✅ | 文章标题；≤ 200 |
| `content` | string | ✅ | Markdown 正文；插图 `![](https://…)` |
| `author` | object | ✅ | **`name`（必填）**；可选 `slug` |
| `excerpt` | string | | ≤ 500；缺省/空 → 无引言 |
| `slug` | string | | 缺省从 title 生成并去重 |
| `postType` | `article`\|`opinion` | | **默认 `opinion`**；正式稿显式传 `article` |
| `status` | `draft`\|`published` | | 默认 `published` |
| `category` | string | | 默认 `General`（自由标签，不是内容类型） |
| `titleZh` / `excerptZh` / `contentZh` | string | | 双语可选 |
| `image` | string | | 封面 URL；http(s) 镜像到 Blob |
| `sourceUrl` | string | | 原文链接 http(s) |
| `readTime` | string | | 可选；缺省自动估算并展示 |
| `featured` | boolean | | 默认 `false` |
| `tags` | string[] | | 最多 12；可逗号分隔字符串 |

不声明、请勿依赖：`author.title`、`author.orgSlug`、顶层 `orgSlug` / `authorTitle` 等历史字段。

### Response `201`

```json
{
  "ok": true,
  "slug": "how-users-adopt-ai-agents",
  "url": "https://blog-lsforum.vercel.app/posts/how-users-adopt-ai-agents",
  "version": 1,
  "status": "published",
  "item": {
    "kind": "external",
    "slug": "how-users-adopt-ai-agents",
    "title": "…",
    "content": "…",
    "contentZh": null,
    "image": "https://….public.blob.vercel-storage.com/covers/…",
    "status": "published",
    "version": 1,
    "createdAt": "2026-07-20T12:00:00.000Z",
    "updatedAt": "2026-07-20T12:00:00.000Z",
    "publishedAt": "2026-07-20T12:00:00.000Z",
    "deletedAt": null
  }
}
```

`item` 为 **ManagedExternalPostResponse**：含列表字段 + 正文 + `status` / `version` / 时间戳等，不仅限于 ExternalListItem。

---

## 封面图（v0.3）

| 合作方传入 | 服务端 | 存入 `ingested_posts.image` |
| ---------- | ------ | --------------------------- |
| 省略 | 无封面，UI 占位 | `null` |
| `https://partner…/tmp.jpg` | 拉取 → Public Blob `covers/{slug}/…` | `https://….public.blob.vercel-storage.com/…` |
| `https://….public.blob.vercel-storage.com/…` | 已托管，跳过 | 原 URL |
| `https://….private.blob.vercel-storage.com/…` | **视为未托管**，尝试重新镜像到 Public | Public URL 或失败时保留原址 |
| `/assets/…` | 站内静态资源 | 原路径 |

**要求：** 公网 http(s)；jpeg/png/webp/gif；≤ 10 MB/张；单张 fetch 超时 20 s。

**临时 URL 语义（重要）：**

- 镜像**成功** → 响应中 URL 已变为 `.public.blob.vercel-storage.com`，此后原临时链可失效。
- 镜像**失败** → 响应仍返回**原始 URL**，你必须保持该 URL 在访客可读期间持续可访问。
- 未配置 Blob → http(s) 原样存储，**你方负责链接长期有效**。

---

## 正文插图（v0.4）

在 `content` / `contentZh` 中使用 Markdown 图片语法，**无单独字段**：

```markdown
第一段。

![Figure 1](https://partner.example/tmp/fig1.png)

第二段。
```

**版式位置**由 Markdown 文档顺序决定，无 `imagePosition` 字段。块级图建议前后各空一行。

| 写法 | 渲染 |
| ---- | ---- |
| 段落后空行 + `![](url)` + 空行 + 下一段 | 段间全宽插图 |
| `文字 ![icon](url) 继续` | 段内 inline 图 |

| Markdown 中的 URL | 服务端 |
| ----------------- | ------ |
| `![](https://partner…/a.png)` | 镜像 → `content/{slug}/inline/…` |
| `![](https://….public.blob.vercel-storage.com/…)` | 跳过 |
| `![](https://….private.blob.vercel-storage.com/…)` | 按外链重新镜像 |
| `![](/assets/…)` | 跳过 |
| HTML `<img>` | **不支持**（渲染时剥离） |

**限制：**

- 与封面相同的内容类型与大小
- 每个 markdown 字段最多 **20** 个不同外链；中英文各算一个字段
- 同 URL 多次出现只镜像一次
- 镜像并发 **4** 路，整次请求图片处理预算 **50 s**；超限后剩余 URL 保持原址
- URL **勿含未编码空格或 `)`**；含特殊字符须 `encodeURI`（解析用正则，非完整 Markdown AST）

临时 URL 规则与封面相同：仅当响应/详情中已改写为 Public Blob URL 后，才可放弃原链。

---

## Partner UAT 清单

1. `POST` `status: draft` → 公开 `GET` 返回 `404`
2. `POST` `status: published` → 公开 `GET` `200`；`item.date` 为日历日；`item.readTime` 有值
3. 带 `image` 的 `POST` → `item.image` 含 **`.public.blob.vercel-storage.com`**
4. `GET /api/v1/posts/:slug` → `content` 内所有 `![](…)` 已改写为 **`.public.blob.vercel-storage.com`**（或 `/assets/`）
5. 对封面 + 每张正文图 `HEAD` → `200`，`Content-Type` 为 `image/*`
6. 浏览器打开文章页，封面与正文图均可见
7. `PATCH` / `DELETE` / `restore` / `revisions` → `404` 或 `405`

```bash
INGEST_API_KEY="..." npm run test:ingestion -- https://blog-lsforum.vercel.app
```

### 本地测试

```bash
cp .env.example .env.local
# vercel env pull .env.local  # POSTGRES_URL, INGEST_API_KEY, Blob 变量
npm install && npm run dev
```

```bash
curl -X POST http://localhost:3456/api/v1/posts \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"title":"Local test","author":{"name":"Sam"},"content":"# Hi\n\n![x](https://example.com/x.png)"}'
```

---

## 公开读接口摘要

### GET `/api/v1/posts`

Query: `page`, `pageSize` (1–50), `type` (`article`|`opinion`|`import`), `org`, `category`, `featured=true`
排序：按发布时间倒序（API 稿含精确时间戳；前台 `date` 只到日）。

### GET `/api/v1/posts/:slug`

列表字段 + `content`, `contentZh`。
`external` 帖子的 `content` 中应为镜像后的 Blob URL。

### Content kinds

| `kind` | 来源 | 路由 |
| ------ | ---- | ---- |
| `post` | `/content/posts` | `/posts/:slug` |
| `import` | `/content/imports` | `/:keyword`（Industry News） |
| `external` | `POST /api/v1/posts` | `/posts/:slug` |

### ExternalListItem（feed / 列表）

```json
{
  "kind": "external",
  "slug": "how-users-adopt-ai-agents",
  "url": "/posts/how-users-adopt-ai-agents",
  "postType": "opinion",
  "title": "How users adopt AI agents",
  "excerpt": "…",
  "category": "AI",
  "date": "2026-07-16",
  "readTime": "4 min read",
  "image": "https://abc.public.blob.vercel-storage.com/covers/…/cover.jpg",
  "authorSlug": "jane-doe",
  "authorName": "Jane Doe",
  "authorTitle": null,
  "orgSlug": null,
  "orgName": null,
  "tags": ["ai", "agents"]
}
```

`date` 为发布日历日；`readTime` 为阅读时间文案（上传时未传则由服务端估算）。

---

## SEO

详情页自动生成：`title` / `excerpt`、canonical、Open Graph、Twitter Card、JSON-LD `Article`。
建议提供清晰 `title`、`excerpt`、`image`、**`author.name`**，及 `tags`。

---

## Errors

```json
{ "error": { "code": "NOT_FOUND", "message": "Post not found" } }
```

| Code | HTTP | When |
| ---- | ---- | ---- |
| `NOT_FOUND` | 404 | 未知 slug/keyword/org；或 draft 的公开读 |
| `VALIDATION_ERROR` | 400 | 非法参数或字段 |
| `UNAUTHORIZED` | 401 | 缺失或错误 `INGEST_API_KEY` |
| `VALIDATION_ERROR` | 503 | 未配置数据库（实现上 code 仍为 `VALIDATION_ERROR`） |
| `VALIDATION_ERROR` | 500 | 写入失败（Postgres 或镜像异常） |

---

## 存储结构

### Postgres `ingested_posts`（API 文章）

| 列 | 说明 |
| --- | --- |
| `slug` | PK |
| `title`, `title_zh`, `excerpt`, `excerpt_zh` | |
| `content`, `content_zh` | Markdown；正文图 URL 在文中 |
| `category`, `post_type`, `status`, `version` | `status`: draft / published / archived |
| `author_name`, `author_title`, `author_id`, `author_slug`, `author_external_id` | 作者冗余 + `ingested_users` 关联 |
| `org_slug`, `org_name` | |
| `image` | 封面 **已服务 URL**（优先 Public Blob） |
| `source_url`, `read_time`, `featured`, `tags` | |
| `created_at`, `updated_at`, `published_at`, `deleted_at` | |
| `source_system` | |

关联表 **`ingested_users`**：`external_id` + `source_system` 唯一，供作者 upsert。

### Vercel Blob（图片二进制）

| 路径 | 用途 |
| ---- | ---- |
| `covers/{slug}/…` | 封面 |
| `content/{slug}/inline/…` | 正文图 |

**必须 Public Store**；仅 `.public.blob.vercel-storage.com` URL 视为已托管。

### Git `/content`（编辑部）

见 [content-guide.md](./content-guide.md)。与 API 路径独立。

---

## 运维：备份

```bash
POSTGRES_URL="postgres://..." npm run backup:posts
POSTGRES_URL="postgres://..." npm run restore:posts -- backups/ingested-posts/<file>.json.gz --confirm
```

`backups/` 已 gitignore。勿将备份提交 GitHub。
