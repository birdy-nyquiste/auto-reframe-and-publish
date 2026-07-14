---
status: accepted
---

# 使用一个可移植的端到端 Skill

项目只维护一个仓库内的 `process-weixin-submissions` Skill，覆盖初始化、微信采集、任务解析、内容处理、Blog 草稿交付、状态审计和显式重试。核心 `SKILL.md` 只保留全流程步骤、分支和完成标准，详细协议通过 references 渐进披露，确定性状态修改由 scripts 完成；Agent 特定的发现目录和 Computer Use 工具仅作为薄适配层，不形成 Codex 与 Claude Code 两套源码。
