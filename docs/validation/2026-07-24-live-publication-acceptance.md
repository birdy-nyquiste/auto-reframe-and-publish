# Ticket 11 真实发布验收（2026-07-24）

## 结论

现有真实微信任务已经通过独立发布操作上传正文引用图片并公开发布到 LSForum。公开页面、图片、作者字段、版本信息和本地审计证据均验证通过，且任务库未持久化发布凭据。

这条证据完成了真实独立发布路径，但不等同于 Ticket 11 要求的真实 `run --publication auto` 验收，也不替代 Ticket 08 的受监督多任务实机矩阵或 Ticket 09 的正式内容规范批准。操作人明确要求不再重复采集并继续暂缓 Ticket 09，因此 Ticket 11 保持未完成，项目 readiness 仍为 `core_validated`。

## 输入产物

- 投稿任务：`task_2bf54d5f74e343e39390840edee99c47`
- 微信文章：`独家| Kimi K3震荡美股，有望最快6个月内港股上市`
- 改写产物：`rewrite_artifact_ready`
- 生成器：`running_agent_v1`
- 洗稿指令：自定义
- 默认提示词：v2，路径与哈希已写入改写 manifest
- 正文引用图片：`source-image-001.png`
- 封面选择：`source-image-001.png`

## 真实发布结果

- 发布运行：`run_83286797349041679d10afb092af40f1`
- 运行操作：`publish`
- 发布任务：`publication_de620bbcff984b5280f5aed9fc2b9915`
- 图片策略：`upload`
- Blob 上传：只上传改写正文实际引用的一个图片；其余采集图片保持本地
- 发布里程碑：`publication_confirmed`
- 内容状态：`published`
- 内容版本：`1`
- ETag：`"1"`
- 公开地址：<https://blog-lsforum.vercel.app/posts/publication-de620bbcff984b5280f5aed9fc2b9915>

公开复核结果：

- 文章页面返回 HTTP 200，并包含预期标题和作者 `birdy-yao`
- 公开图片返回 HTTP 200，`image/png`，830×830，405,428 bytes
- 正文图片 URL 与封面 URL 指向同一内容寻址 Blob 资产

## 审计与安全

- 发布前固定 publication ID、slug、改写 commit、作者字段、目标 adapter、图片计划和完整请求。
- 发布聚合保留准备、发送开始、原始响应、标准化响应和事件链。
- 正常发布只执行公开创建及受认证的 `manage=true` 确认，没有调用 PATCH、软删除、恢复或 revisions。
- API key 与 Blob token 只从显式 `.env` 读取；任务库、报告和 Git 文件中未发现密钥值。
- 改写产物保持不变；发布呈现仅把正文中的本地图片引用替换为固定公网 URL，并记录前后正文哈希。

## 相关场景覆盖

确定性自动化套件已覆盖：

- 省略或明确 `none` 时不发布
- `auto` 只为本次运行中新完成的产物创建发布任务
- 图片缺失阻塞、图片上传计划和封面映射
- 多任务排序、单任务失败隔离和重复投稿
- 未知发布结果禁止盲目重发
- 内容及发布中断恢复
- 显式重试和重试耗尽
- 来源注入不能扩大发布或本地文件能力
- 正常与异常路径的脚本化剪贴板清理

这些测试验证确定性代码和状态机，但不冒充尚未执行的多任务真实微信 UI 验收。

## 第二条真实任务：自动发布选择与图片恢复

操作人随后在文件传输助手提交了一条新任务，并明确选择自动发布：

- 投稿任务：`task_e68316be75f34ed4a2f63953db5c60a5`
- 微信文章：`Chase Sapphire Preferred (CSP) 信用卡【100k 开卡奖励 即将过期】`
- 自动运行：`run_8591e96f8b104e499859f121498c3fb7`
- 默认提示词：v2
- 采集结果：完整复制正文、2 张原始静态图，以及 1 个 17 帧 GIF 的静态首帧
- 改写产物：`rewrite_artifact_ready`

真实 `run --publication auto` 确实只选择了本次新完成的产物，但默认
`preserve` 图片策略无法为正文中的本地图片生成公网 URL。自动运行因此创建
`publication_6606ccd616d342cb93769696814e8fe2` 并以
`needs_configuration/public_image_urls_missing` 停止，没有向 Blog 发送缺图正文。
这是一条正确的安全阻塞，也证明当前自动运行仍未把已有 Blob 上传能力接入。

在不重新采集、不重新改写的前提下，同一改写产物随后通过独立发布操作恢复：

- 恢复运行：`run_fcbfe042d2834820b9ced896f3d27bd5`
- 发布任务：`publication_b8dfa826e26f461cb6429cb40436eb59`
- 图片策略：`upload`
- 封面：`source-image-001.jpg`
- 正文图片：信用卡首图和历史奖励趋势图
- 发布里程碑：`publication_confirmed`
- 内容状态：`published`
- 内容版本：`1`
- ETag：`"1"`
- 公开地址：<https://blog-lsforum.vercel.app/posts/publication-b8dfa826e26f461cb6429cb40436eb59>

独立复核确认公开页面、Content API、封面 Blob 和趋势图 Blob 均返回 HTTP
200，公开 API 正文包含 Blob URL。动画 GIF 只保留静态首帧作为采集证据，
改写 Agent 未在发布正文中引用该推广二维码图片。

这条任务完成了操作人的实际发布目标，同时暴露出当时 Ticket 11 的剩余缺口：
让 `run --publication auto` 接受显式上传配置并在同一个运行内完成图片上传和
发布。后续实现已增加 `--image-policy upload --env-file`、artifact v2 的 Agent
封面选择及同运行 Blob 上传，并通过确定性 CLI 测试；由于本条真实任务仍是在
实现前依靠独立 `publish` 恢复，自动发布验收项要等下一条真实任务直接跑通后
才能勾选。

## 当前 readiness

- validation scope：`core_validated`
- 投稿任务：2 个 `rewrite_artifact_ready`
- 发布任务：2 个 `publication_confirmed`，另有 1 个可审计的 `needs_configuration`
- 内容 blocker：无
- 发布 blocker：历史自动运行保留 1 个实现前的图片配置阻塞；新实现待下一条真实任务复验
- writer lock：无
- Ticket 08：仍需受监督多任务实机矩阵
- Ticket 09：按操作人决定暂缓，正式规范尚未批准
- Ticket 10：完成
- Ticket 11：真实独立发布路径已通过，其余阻塞条件未解除
