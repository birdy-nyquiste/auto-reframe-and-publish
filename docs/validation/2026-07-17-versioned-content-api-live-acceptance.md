# 版本化 Content API 真实验收（2026-07-17）

## 结论

在操作人要求重新测试更新接口后，使用唯一 `[UAT TEST]` draft 对部署中的 Content API v1.2.0 完成全部新增能力验收。第二次完整运行覆盖创建、管理读取、条件更新、版本冲突、软删除、恢复和 revisions，所有预期均通过；测试 draft 从未公开，最终再次软删除。

## 契约校正

同事补充消息要求 PATCH 发送 `If-Match: "<version>"`，但第一次真实 UAT 按该规则发送当前 version 1 时，服务端返回 `412`。随后读取部署中的 `/api/v1/openapi.json`，确认当前版本为 `1.2.0`，实际要求：

```http
X-Post-Version: "<current version>"
```

OpenAPI 还定义缺少或非法版本头为 `428`。适配器、localhost fixture、外部接口参考和 Ticket 12 已按部署契约修正。失败的第一条测试 draft `uat-versioned-content-api-20260718-032904-ca6fd2` 已软删除且公共 GET 为 `404`。

## 完整通过的真实生命周期

测试 slug：`uat-versioned-content-api-20260718-033404-1aafef`

| 能力 | 真实结果 | 关键证据 |
| --- | --- | --- |
| `POST /posts` draft | `201` | status `draft`，version `1`，ETag `"1"` |
| 公共隐藏 draft | `404` | draft 未进入公共详情 |
| `GET ?manage=true` | `200` | 返回 draft、version `1`、`deletedAt: null` |
| 当前版本 PATCH | `200` | `X-Post-Version: "1"`；version 增至 `2`，ETag `"2"` |
| 过期版本 PATCH | `412` | error code `VERSION_CONFLICT`，currentVersion `2` |
| 软删除 | `200` | version `3`，ETag `"3"`，公共 GET `404` |
| 管理读取软删除 | `200` | 返回非空 `deletedAt` |
| 恢复 | `200` | version `4`，ETag `"4"`，`deletedAt: null` |
| revisions | `200` | 最新优先返回 create/update/delete/restore 四个快照 |
| 初次最终清理 | `200` | 再次软删除至 version `5`，公共 GET `404` |
| 恢复后公共隐藏复核 | `200 / 404 / 200` | restore 至 version `6` 后公共 GET 仍为 `404`，随即再次软删除至 version `7` |

历史只通过 API 读取，没有尝试修改历史或彻底删除。密钥仅从交互式运行环境读取，没有写入请求证据、仓库文件、日志或报告。

## 本地回归边界

localhost 合约测试覆盖所有新增管理方法、Bearer 认证、`X-Post-Version`、成功 PATCH、412、软删除、恢复、revisions、稳定作者身份字段和嵌套错误结构。本次实现完成后：

- `tests.test_lsforum_publication`：21 个测试全部通过；
- 全仓库：61 个测试全部通过；
- mypy：24 个源文件无错误；
- Skill 快速校验：通过；
- `lsforum_blog.py` 的语句/分支综合源码覆盖率：76%。

因此这里的“100% 接口覆盖”指本次更新列出的 6 个 API 能力及关键并发错误路径全部有真实证据，不代表外部服务的未公开实现分支或本地适配器源码具有 100% 源码覆盖率。
