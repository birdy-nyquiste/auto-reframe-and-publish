# macOS 微信整篇文章实机 tracer（2026-07-24）

## 结论

当前 Mac 已完成一条真实微信任务从文件传输助手输入窗口、整篇文章采集到真实 Agent 改写产物的受监督 tracer。正文来自微信文章窗口内的复制粘贴，全部静态图片按文章顺序采集，任务最终达到 `rewrite_artifact_ready`；运行采用默认的不发布选择，没有创建发布任务或请求 Blog 凭据。

该结果完成了 Ticket 08 的单篇完整文章 tracer，并验证 Ticket 11 的默认“不发布”路径，但不等于完整多场景套件通过，readiness 仍为 `core_validated`，不得宣称 `macos_validated` 或 `ready`。

## 环境

- macOS 27.0（Build 26A5378j）
- WeChat 4.1.10（Build 268880）
- Codex CLI 0.146.0-alpha.3.1
- Computer Use plugin 1.0.1000502
- 会话：文件传输助手
- 窗口特征：文件传输助手消息列表可由辅助功能定位；公众号文章正文通过微信内文章子窗口的复制能力读取；静态图片通过图片右键菜单的“保存图片”或带证据的截图裁剪采集

如果微信文章窗口、右键菜单、复制行为或辅助功能结构发生变化，本记录对应的实机结论需要重新验证。

## 输入与边界

- 基线标记：`marker_a239d674f8b4a95c4cce422d688c3151`
- 采集标记：`marker_6e0883f4fc644d887ec7ae4f2cad9cd3`
- 恢复标记：`marker_59b3c581622e3a1bd086a236ba69cc90`
- 修复验证标记：`marker_9581fecea7c5d5affdfdc65440ed3e0d`
- 任务头：`#投稿`、`author.name: birdy-yao`、`洗稿指令：加强爱国主义精神`
- 文章：`独家| Kimi K3震荡美股，有望最快6个月内港股上市`
- 来源公众号：投资界
- 发布选择：`none`
- 任务：`task_2bf54d5f74e343e39390840edee99c47`
- 初始运行：`run_c43dc864028b465ba746c4fbe50fb4d2`
- 成功恢复运行：`run_850bd80cbaed422d841e12559975b7ba`

任务头中的全角 `：` 被正常解析；实现与回归测试同时确认字段分隔符接受半角 `:` 和全角 `：`。

## 已验证行为

1. Computer Use 在文件传输助手中建立并回读批次标记，只读取相邻标记之间的新消息。
2. `#投稿` 任务头与紧随其后的单篇公众号文章严格配对；洗稿指令属于该任务，没有被误判为独立任务。
3. 在微信文章窗口内执行 `Command+A`、`Command+C`，取得 4,293 字符正文。正文没有通过 OCR、浏览器或网页接口构造。
4. 遍历到文章末尾，共记录 15 个媒体位置：13 个静态图片位置和 2 个嵌入视频位置。当前产品只支持静态图，因此视频未下载、未转写，并在 manifest 中保留警告。
5. 13 个静态图片位置中，12 次使用微信“保存图片”取得原始字节；末尾星标提示图无法取得原始文件，使用 1 次 `viewport_crop`，同时保存完整视口、裁剪坐标和哈希。重复装饰图按文章位置保留重复引用。
6. 采集 manifest 报告 `body_text`、`article_end_observed`、`all_static_images_captured` 和 `complete` 均为 `true`。
7. 初始真实 Codex 子进程因桌面沙箱无法写入运行状态而失败。该类启动失败和超时现在属于有界 `rewrite_generation` 重试，预算为 2；旧任务库中这两个精确错误码的永久失败可通过显式 `retry` 安全升级。
8. 恢复运行在空的新输入窗口中继续处理已有任务，没有重复创建任务。真实 Agent 生成并通过确定性校验后，任务达到 `rewrite_artifact_ready`。
9. 成功里程碑会清除原有重试 blocker；迁移修复也会在确认现有改写 commit、manifest 和内容有效后，以 `blocker_changed` 事件清除旧版本留下的矛盾 blocker。
10. 运行使用 `publication_selection: none`，任务库中的 publication 数量为 0；没有调用 Blog、Blob 或读取其凭据。
11. 退出文章窗口后，剪贴板被替换为 `clipboard-cleared` 并通过未发送的微信输入框回贴验证；文章标题和批次标记均不再存在于剪贴板。

## 产物与最终状态

- 改写正文：`task-repository/tasks/task_2bf54d5f74e343e39390840edee99c47/rewrite/content.md`
- 改写 manifest：`task-repository/tasks/task_2bf54d5f74e343e39390840edee99c47/rewrite/manifest.json`
- 采集 manifest：`task-repository/tasks/task_2bf54d5f74e343e39390840edee99c47/raw/capture/manifest.json`
- 恢复运行报告：`task-repository/runs/run_850bd80cbaed422d841e12559975b7ba/report.md`
- 最终任务里程碑：`rewrite_artifact_ready`
- 最终 blocker：无
- 任务数：1
- 发布数：0
- readiness：`core_validated`

## 回归验证

- 全角与半角任务头分隔符测试：通过
- Codex 运行时失败、空窗口恢复、成功后 blocker 清理、旧永久失败显式升级测试：通过
- `compileall`：通过
- 全仓库 `unittest`：86 个测试全部通过

沙箱内首次运行全仓库测试时，22 个 localhost fixture 测试因系统拒绝绑定本地端口而报 `PermissionError`；在允许本地 socket 的同一代码状态下重跑后，86 个测试全部通过。该限制与应用断言无关。

## 尚未完成

- 多任务排序、相同内容重复投稿、当前标记后消息排除和单任务失败隔离的组合实机套件。
- 更多中断点及显式重试边界的受监督实机覆盖。
- Ticket 11 的操作人明确选择自动发布路径及受控真实 Blog 验收。
- 正式改写规范 Ticket 09；操作人已明确暂缓，本次继续使用当前默认提示词 v2。
