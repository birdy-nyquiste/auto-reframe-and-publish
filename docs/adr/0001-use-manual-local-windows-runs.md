---
status: accepted
---

# 在固定 Windows 主机上人工触发本地运行

生产流程由固定 Windows 采集主机上的 Codex 或 Claude Code 本地执行，运营微信号长期登录同一主机；项目不采用轮询、持续监听、远程 Mac 控制或多机采集。操作者必须显式调用 Skill 才能启动 Computer Use，每次运行结束后退出，以换取桌面状态、剪贴板、检查点和故障恢复处于同一可见边界。
