# LSForum 真实接口验收（2026-07-17）

## 结论

在操作人明确授权后，项目使用一条醒目标记为 `[UAT TEST]` 的纯文本 mock 投稿完成了真实 LSForum 写入和公开回读：内容任务达到 `rewrite_artifact_ready`，独立发布任务达到 `publication_confirmed`，服务端返回的 slug、标题、作者、分类、类型、标签和正文与固定请求一致。

## 公开证据

- Run ID: `run_36a6e4e3883b4f88a4978a370b160b2b`
- Task ID: `task_0668290a04474abd9759a05f9e5624d8`
- Publication ID: `publication_23846b2a21ba44b78c5ae7080ccf4d64`
- Public URL: <https://blog-lsforum.vercel.app/posts/publication-23846b2a21ba44b78c5ae7080ccf4d64>
- POST result: HTTP `201`
- Independent GET result: `kind: external`，且固定字段和正文匹配

任务库检查确认运行时密钥没有写入请求、响应、任务、事件或报告。真实任务库位于 Git 忽略的本地运行目录，不作为仓库 fixture 提交。

## 同次验收发现的问题

首次配置把密钥包在 Unicode 弯引号中，客户端在本地构造 Header 时触发未捕获的编码异常。该请求没有到达服务器，但留下了 `request_ready` 发布任务。后续实现因此补充：

- 非 ASCII、包含包裹引号或首尾空白的密钥在任何网络请求前进入 `api_key_invalid_format`；
- 发布 attempt 区分 `prepared` 与 `send_started`；
- 明确未开始外部调用的固定请求可在后续 `auto` 运行中继续；
- 外部调用可能已经开始时只允许 GET 确认，不允许重复 POST；
- 中断 run 与恢复 run 保留 publication 关联。

## 未覆盖范围

本次使用 `scripted_agent_fixture_v1`，且文章不含图片。因此它不证明正式改写质量、真实 Agent 生成、图片公网托管、Windows Computer Use 或真实微信采集可用，项目整体 readiness 仍为 `core_validated`。

本次验收发生在版本化 Content API 更新之前，因此也没有验证新响应的 version/ETag、带认证的 `manage=true` 读取、PATCH、软删除、恢复或 revisions。新增能力目前只有 localhost 合约测试证据；不得把这份旧 UAT 误解为生产接口新能力已完成真实验收。
