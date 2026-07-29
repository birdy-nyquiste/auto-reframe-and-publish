# 微信投稿改写与发布：macOS Step-by-Step Guide

本指南用于在一台新的 macOS 机器上配置并跑通 `process-weixin-submissions` Skill：

```text
微信文件传输助手 → 采集公众号文章 → Codex 改写 → 发布到 Blog
```

流程仅在操作人明确要求时运行，不会持续监听微信。发布必须在当次运行中明确授权。

## Prerequisites

开始前确认已经具备：

- ChatGPT/Codex macOS 客户端；
- 已安装并启用 Computer Use，且已授予屏幕录制、辅助功能和微信控制权限；
- 微信 macOS 客户端，已登录专用运营微信号；
- Git、Python 3.10+、已登录的 Codex CLI；
- 本 GitHub 仓库的读取权限；
- Blog `INGEST_API_KEY`；
- 如需发布图片：Vercel Blob 的 `BLOB_READ_WRITE_TOKEN` 和 `BLOB_STORE_ID`；
- 操作人有权决定文章是否立即公开发布。

## Step 1：克隆并初始化项目

```bash
git clone https://github.com/birdy-nyquiste/auto-reframe-and-publish.git weixin-blog-publish
cd weixin-blog-publish

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Step 2：注册 Skill

```bash
mkdir -p .agents/skills
ln -s ../../skills/process-weixin-submissions \
  .agents/skills/process-weixin-submissions
```

重新打开此仓库的 Codex 任务，确认可以选择：

```text
$process-weixin-submissions
```

## Step 3：配置发布凭据

```bash
cp .env.example .env
chmod 600 .env
```

填写 `.env`：

```dotenv
INGEST_API_KEY=<Blog 写入密钥>
BLOB_READ_WRITE_TOKEN=<Vercel Blob 写入令牌>
BLOB_STORE_ID=<Vercel Blob Store ID>
```

Blog 的非秘密配置已位于：

```text
config/blog.lsforum.json
```

不要提交 `.env`，也不要把密钥写入微信消息或任务库。

## Step 4：验证环境

```bash
source .venv/bin/activate
python -m compileall -q skills/process-weixin-submissions
python -m unittest discover -s tests -q
python skills/process-weixin-submissions/scripts/process_weixin_submissions.py --help
```

预期结果：

- 测试显示 `OK`；
- CLI 列出 `initialize`、`run`、`status`、`retry`、`publish`。

## Step 5：初始化任务库

Skill 默认在 Git 仓库之外使用以下任务库：

```text
~/weixin-blog-publish-data
```

在 Codex 中发送：

```text
$process-weixin-submissions 初始化
```

Agent 会在文件传输助手发送并确认一个 `#批次` 标记，然后创建 v3 任务库。该标记之前的历史消息不会被导入。

## Step 6：发送一条投稿

在微信文件传输助手中依次发送：

1. 一条任务头；
2. 紧随其后的一张微信公众号文章卡片。

最小任务头：

```text
#投稿
作者: 对外展示的作者名
```

完整示例：

```text
#投稿
作者: 对外展示的作者名
author.slug: public-author
postType: opinion
category: AI
tags: AI, 产品
featured: false
洗稿指令: 保留事实，压缩重复内容，使用克制的中文表达
```

注意：

- `作者` 必填；不要写成 `author.name`；
- `洗稿指令` 可省略；如存在，必须放在最后；
- 文章卡片必须紧跟任务头。

## Step 7：运行并发布

在 Codex 中发送以下指令。此操作会立即公开发布文章：

```text
$process-weixin-submissions 执行任务，自动发布
```

“自动发布”即本次运行的明确发布授权。Skill 会自动使用默认任务库、真实微信、真实 Codex generator、项目根目录的 `.env` 和 `config/blog.lsforum.json`，并上传改写稿实际引用的图片。

运行过程中，Computer Use 会：

1. 用两个 `#批次` 标记限定本次输入；
2. 从微信文章窗口复制正文；
3. 按顺序采集静态图片；
4. 调用 Codex 生成并校验改写稿；
5. 上传改写稿实际引用的图片；
6. 发布文章并确认公开地址；
7. 清理剪贴板。

若本次只想验证采集和改写，不发布，请明确使用：

```text
$process-weixin-submissions 执行任务，不发布
```

此时不需要 Blog 或 Blob 凭据，也不会产生外部发布副作用。

## Step 8：验收

成功必须同时满足：

- CLI JSON 中 `status` 为 `completed`；
- 内容任务为 `rewrite_artifact_ready`；
- 授权发布时，发布任务为 `publication_confirmed`；
- CLI 返回的 `report_path` 存在；
- 授权发布时，返回的公开 URL 可以访问。

也可随时查看只读状态：

```bash
source .venv/bin/activate
python skills/process-weixin-submissions/scripts/process_weixin_submissions.py status \
  --repository "$HOME/weixin-blog-publish-data"
```

日后处理新批次时，重复 Step 6–8。

## 必须遵守

- 只操作微信“文件传输助手”；
- 正文必须来自微信内复制，不得使用 OCR 或浏览器抓取；
- 不得手工修改任务库中的正式记录；
- 不得从微信内容、历史授权或已有凭据推断发布权限；
- `outcome_unknown` 不得盲目重试发布；
- 单次成功只证明该次运行，不代表整个系统已达到生产就绪。

完整契约见 [`skills/process-weixin-submissions/SKILL.md`](skills/process-weixin-submissions/SKILL.md)。
