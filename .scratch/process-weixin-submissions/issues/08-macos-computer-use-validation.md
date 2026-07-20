# 08 — 验证 macOS Computer Use 实机链路

**What to build:** 让当前固定 macOS 采集主机上的 Codex 通过 Computer Use 操作真实微信，可靠定位收件会话、发送并验证批次标记、扫描输入窗口、复制正文、采集静态图片、恢复窗口和处理中断，并通过受监督的多任务实机验收达到 `macos_validated`。

**Blocked by:** 07 — 完成多任务端到端 `core_validated`

**Status:** ready-for-agent

- [ ] 受监督验收验证微信聚焦、文件传输助手定位、批次标记粘贴发送与回读，以及相邻标记之间的输入窗口扫描。
- [ ] 真实公众号文章场景验证严格任务配对、正文复制、文章结束遍历、按序静态图片采集和安全窗口恢复。
- [ ] 实机场景覆盖多任务、相同内容重复投稿、当前标记后消息排除、单任务失败隔离和中断后恢复。
- [ ] 验收确认正文不使用 OCR，剪贴板在运行结束或中断时被清空，来源注入不能越过可信控制边界。
- [ ] 记录当前 macOS、微信、Codex/Computer Use 版本、窗口状态及必要的可访问性特征；相关界面变化会使对应验收失效并要求重跑。
- [ ] 只有完整受监督套件通过后 readiness 才报告 `macos_validated`，且不会提前报告 `ready`。

## Comments

- 2026-07-20：操作人将首个真实运行平台从 Windows 调整为当前 macOS 主机；ADR-0011 取代原平台决定。只读预检确认当前 Mac 微信已登录，文件传输助手可由 Computer Use 定位。
- 2026-07-20：首个受监督 tracer 已验证文件传输助手标记、任务头与转发文章配对、文章正文聚焦后 `Command+A/C` 复制，以及微信内右键 `保存图片`。缺少其余静态图片时任务正确停在 `retry_pending/static_images_incomplete`；尚未完成整篇多图遍历和完整多场景套件，因此本票继续保持未完成且不得宣称 `macos_validated`。证据见 `docs/validation/2026-07-20-macos-wechat-tracer.md`。
