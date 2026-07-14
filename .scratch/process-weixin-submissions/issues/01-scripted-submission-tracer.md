# 01 — 打通一条脚本化投稿纵向链路

**What to build:** 让操作人能够通过仓库内的 canonical Skill 骨架，以脚本化输入窗口提交一条标准投稿，并看到系统创建运行与投稿任务、生成一个可验证的替代改写产物、向 fake Blog API 创建发布草稿，最后留下完整状态和运行报告。这是后续能力共同复用的第一条端到端 tracer bullet。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 一条包含有效任务头和一篇来源文章的脚本化输入，能够从运行开始一路推进到已确认的 fake Blog 发布草稿。
- [ ] 运行结果包含可验证的运行记录、投稿任务记录、改写产物、交付结果和面向操作人的报告。
- [ ] canonical Skill 已具备 initialize、run、status、retry 四个操作的可扩展入口，其中本票据覆盖的纵向链路可以通过该 Skill 调用。
- [ ] 自动化测试从用户可观察结果验证整条链路，而不是只验证孤立内部组件。

