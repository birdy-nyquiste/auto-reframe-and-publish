# macOS 微信实机 tracer（2026-07-20）

## 结论

当前 Mac 已验证真实微信中的批次边界、任务配对、正文复制和单张静态图片原图保存。该文章仍缺其余静态图片，因此任务按设计停在 `retry_pending / static_images_incomplete`。这是一条真实的安全失败与图片采集 tracer，不等于 Ticket 08 完成，也不支持宣称 `macos_validated`。

## 环境

- macOS 27.0（Build 26A5378j）
- WeChat 4.1.10
- Codex CLI 0.145.0-alpha.18
- Computer Use plugin 1.0.1000451
- Holo runtime 0.1.8（仅用于微信子窗口的视觉定位；正式证据仍由文件和任务库校验）

## 输入与边界

- 会话：文件传输助手
- 基线标记：`marker_bac09ddc81614388973bdeba7f481c8b`
- 结束标记：`marker_1cc498866c634f6ab28f4cc26ca749e7`
- 任务头：`#投稿` + `目标: macos-uat`
- 文章：`Anthropic发布「AI原生创业公司」手册：涵盖全流程四大核心阶段，一人公司法典来了`
- 发布选择：`none`

## 已验证行为

1. Computer Use 在文件传输助手内粘贴并发送边界标记，回读确认标记存在。
2. 任务头和其后紧邻的公众号文章卡片被视为一个任务；更早的孤立标记不进入窗口。
3. 打开文章后先点击正文取得焦点，再执行 `Command+A`、`Command+C`。将剪贴板粘回未发送的微信输入框进行校验，得到 58,285 字符，开头为预期文章标题而非任务头；随后清空输入框。
4. 未完成静态图片采集时，CLI 创建运行 `run_18cbf74222334a7cbf87f62ce45bf699` 和任务 `task_d2c69b1a462645d8936ac45e1c4378df`，任务结果为 `retry_pending / static_images_incomplete`，没有生成改写或发布产物。
5. 将文章子窗口最大化后，右键首张正文图片出现 `复制 / 转发 / 保存图片` 菜单。选择 `保存图片` 并通过 macOS 保存对话框写入任务库 `tmp/` 暂存区。
6. 首张图片文件验证为 PNG、1080×461、478,949 bytes；SHA-256 为 `98740e2d9e045715efbcdde570ab0e2772f49d5a619c77770252dbc15df1b198`。
7. 另用明确标记为测试数据的无图片 captured window 调用本机真实 `codex exec`，任务 `task_7a87e1d3c83c4bf18299f667fa3c436f` 达到 `rewrite_artifact_ready`。manifest 记录 `generator: running_agent_v1`、默认提示词 v1 路径与哈希、可信目标 `macos-live-generator`；`publication_selection` 为 `none`，没有发布结果。该步骤只验证真实改写生成器，不冒充微信实采内容。
8. 退出文章窗口后，通过微信输入框将剪贴板替换为 `clipboard-cleared`，回贴验证该哨兵文本后清空输入框；文章正文和链接不再留在剪贴板中。

## 本次形成的实现约束

- 正文必须来自微信内复制粘贴，不使用 OCR。
- 图片必须在微信文章窗口内逐个右键处理；优先保存原图，保存不可用时才允许记录截图裁剪降级。
- 浏览器抓取不属于正式采集流程。
- 微信保存的文件只能从当前任务库 `tmp/` 目录导入；解析真实路径后越界或通过符号链接逃逸都会形成永久无效采集失败。
- 文件存在、静态图片类型和哈希校验成功后，才能把该图片计入 `all_static_images_captured`。
- macOS marker 必须严格符合 `marker_<32位小写十六进制>`；captured window 中任何 marker 形状的普通文本也会被拒绝。
- macOS 默认调用真实 Codex generator；显式 scripted override 仅供验证，且不能与自动发布组合。

## 尚未完成

- 遍历并保存该长文的全部静态图片，确认文章末尾与图片出现顺序。
- 用完整多图证据完成一次真实 `rewrite_artifact_ready` tracer。
- Ticket 08 要求的多任务、重复投稿、标记后消息排除、单任务故障隔离、中断恢复和剪贴板最终清理套件。
