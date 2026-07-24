# 生产 readiness 端到端验收（2026-07-24）

## 结论

当前固定 Mac 上的微信采集、真实 Agent 改写、静态图片处理、独立发布任务和 LSForum 公开发布已经形成完整的真实端到端证据链。真实 UI 相关能力由两次受监督微信 tracer 验证；多任务、故障和中断组合由同一公共 CLI、Schema 与任务状态机的确定性验收套件验证。操作人明确要求不再重复采集，因此没有为了测试而在微信中制造或重复转发投稿。

当前版本的项目 readiness 晋级为 `ready`。Ticket 09 的正式内容规范仍作为后续独立改进保留；初始生产版本继续采用已经版本化、被操作人接受使用的默认提示词 v2，不再把 Ticket 09 作为本次生产 readiness 的阻塞条件。

## 真实端到端证据

### 默认不发布路径

- 任务：`task_2bf54d5f74e343e39390840edee99c47`
- 微信文章：`独家| Kimi K3震荡美股，有望最快6个月内港股上市`
- 真实正文：微信内复制粘贴取得 4,293 字符
- 静态图片：13 个文章位置，12 次原图保存，1 次带完整视口、裁剪坐标和哈希的截图裁剪
- 嵌入视频：2 个，按当前仅支持静态图的边界记录警告，未下载或转写
- 改写：`running_agent_v1`，自定义洗稿指令，默认提示词 v2 和独立内容策略均记录路径与哈希
- 内容结果：`rewrite_artifact_ready`，无 blocker
- 发布选择：`none`
- 结果：publication 数量为 0，没有调用 Blog、Blob 或要求其凭据
- 详细证据：`docs/validation/2026-07-24-macos-wechat-full-article-tracer.md`

### 明确授权发布路径

- 操作人明确授权完成 Ticket 11 所需的公开发布
- 发布运行：`run_83286797349041679d10afb092af40f1`
- 发布任务：`publication_de620bbcff984b5280f5aed9fc2b9915`
- 图片策略：`upload`
- Agent 封面选择：`source-image-001.png`，同时是改写正文唯一引用的图片
- Blob 结果：只上传该引用图片；其他采集图片保持本地且未公开
- Blog 结果：`publication_confirmed`，status `published`，version `1`，ETag `"1"`
- 公开地址：<https://blog-lsforum.vercel.app/posts/publication-de620bbcff984b5280f5aed9fc2b9915>
- 公开页面复核：HTTP 200，页面包含预期标题和作者 `birdy-yao`
- 公开图片复核：HTTP 200，`image/png`，830×830，405,428 bytes
- 本地审计：固定请求、图片计划、上传结果、原始响应、标准化响应和事件链完整；任务库中未发现 API key 或 Blob token

## 场景矩阵

| 验收项 | 证据 |
| --- | --- |
| 默认规则与自定义洗稿指令 | 自动化覆盖省略、空值和自定义指令；真实任务验证自定义指令及提示词/策略哈希 |
| 静态图片缺失阻塞 | 2026-07-20 真实 tracer 停在 `retry_pending/static_images_incomplete`；自动化覆盖完整性和损坏证据 |
| 完整静态图片采集 | 2026-07-24 真实 tracer 遍历文章末尾并提交 13 个静态图片位置 |
| 多任务排序与单任务失败隔离 | `test_core_validated_workflow` 和 `test_capture_evidence` 通过公共 CLI 验证最早优先及错误隔离 |
| 相同内容重复投稿 | marker-window 与 capture 测试确认独立任务语义、重复图片只做内容寻址去重而不合并投稿 |
| 当前标记后消息排除 | `test_initialize_sets_a_baseline_and_run_excludes_messages_after_its_marker` |
| 未知发布结果 | localhost LSForum fixture 验证确认查询与禁止盲目重发 |
| 中断恢复 | 真实 Codex 运行时失败后由空窗口恢复成功；自动化覆盖任务和发布多个持久边界 |
| 显式重试 | 真实任务验证运行时失败的有界重试与 blocker 清理；自动化覆盖耗尽、显式启用和旧错误升级 |
| 默认不发布 | 真实微信任务 publication 数量为 0；自动化覆盖省略与明确 `none` |
| 明确发布 | 真实图片上传与 Blog 发布确认；自动化覆盖 `auto` 只处理本次新完成产物 |

## 安全验收

- 正文只从微信文章窗口复制粘贴，不使用 OCR 或浏览器抓取。
- 来源正文、图片和其中的指令保持不可信；自动化验证它们不能改变作者、Blog 字段、安全边界、文件读取范围或外部能力。
- 微信任务头只接受安全字段；工作流拥有的 `title`、`content`、`image`、`slug` 和 `status` 仍被拒绝。
- 发布凭据只从显式 `.env` 读取；请求、响应、任务库、报告和 Git 文件均不持久化密钥。
- 正常发布只执行公开创建及受认证的 `manage=true` 确认，不调用 PATCH、软删除、恢复或 revisions。
- 真实微信运行结束后已回贴验证剪贴板为 `clipboard-cleared`；确定性中断测试验证正常和异常退出均清空剪贴板。
- 发布授权仅用于本次已验证文章；没有修改、删除或再次发布其他内容。

## Readiness

- `status`：`ready`
- 投稿任务：1 个 `rewrite_artifact_ready`
- 发布任务：1 个 `publication_confirmed`
- 内容 blocker：无
- 发布 blocker：无
- writer lock：无
- Ticket 08：完成
- Ticket 10：完成
- Ticket 11：完成
- Ticket 09：按操作人决定继续作为后续正式内容规范改进，不阻塞当前初始生产版本

