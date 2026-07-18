# 01 — 打通一条脚本化投稿纵向链路

**What to build:** 让操作人能够通过仓库内的 canonical Skill 骨架，以脚本化输入窗口提交一条标准投稿，并看到系统创建运行与投稿任务、生成一个可验证的替代改写产物，并在本次明确选择自动发布时通过 fake Blog adapter 完成独立发布任务，最后留下完整状态和运行报告。这是后续能力共同复用的第一条端到端 tracer bullet。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

**Resolution:** completed

- [x] 一条包含有效任务头和一篇来源文章的脚本化输入，能够从运行开始一路推进到已确认的 fake Blog 独立发布任务。
- [x] 运行结果包含可验证的运行记录、投稿任务记录、改写产物、发布结果和面向操作人的报告。
- [x] canonical Skill 已具备 initialize、run、status、retry 四个操作的可扩展入口，其中本票据覆盖的纵向链路可以通过该 Skill 调用。
- [x] 自动化测试从用户可观察结果验证整条链路，而不是只验证孤立内部组件。

## Comments

- 2026-07-17：按 ADR-0009 将早期“发布草稿”表述修正为显式 opt-in 的独立发布任务。`tests.test_scripted_submission` 与 `tests.test_opt_in_publication` 共 8 个定向测试通过。
