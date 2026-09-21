# 接口契约

所有浏览器接口基址为 `http://localhost:8080/api/v1`。除认证和健康检查外，必须携带：

```http
Authorization: Bearer <jwt>
```

Java 普通响应采用 `{ "code": 200, "message": "success", "data": ... }`。

## 认证

- `POST /auth/register`：`{ "username", "password" }`
- `POST /auth/login`：`{ "username", "password" }`

通过 HttpOnly Cookie 建立会话，响应体只返回 `userId` 和 `username`；JWT 不返回给 JavaScript。

## 会话

- `POST /sessions`：创建会话。
- `GET /sessions`：按更新时间倒序查询。
- `GET /sessions/{id}/messages`：读取消息。
- `DELETE /sessions/{id}`：删除会话及消息。

## 对话

- `POST /chat`：同步 JSON 回答。
- `POST /chat/stream`：SSE 流式回答。

请求字段：`session_id`、`message`、`knowledge_base_ids`。`user_id` 由网关注入。

SSE 事件：

- `meta`：意图和引用片段。
- `token`：`{ "content": "..." }`。
- `memory`：待确认记忆。
- `done`：完成。
- `error`：错误信息。

## 资料库

- `POST /knowledge/base`
- `GET /knowledge/base/list`
- `DELETE /knowledge/base/{id}`
- `POST /knowledge/document/upload`：multipart，字段 `kbId`、`file`。
- `GET /knowledge/base/{id}/documents`
- `GET /knowledge/document/{id}/status`
- `DELETE /knowledge/document/{id}`：异步删除原文件和该文档的全部向量片段。
- `POST /knowledge/document/{id}/reparse`：复用原文件重新解析，保留文档 ID，完成后替换旧片段。
- `POST /knowledge/document/{id}/replace`：上传替换文件，创建新版本并复用文档 ID 重建索引。
- `GET /knowledge/document/{id}/versions`：列出文件版本、SHA-256、大小和当前版本状态。
- `POST /knowledge/document/{id}/versions/{version}/restore`：恢复指定原文件版本并重建索引。

文档状态：`parsing -> ready | failed`；删除时为 `deleting`，删除任务失败时为 `delete_failed`。

## 记忆

- `GET /memory`：读取画像。
- `POST /memory/write`：手动补充。
- `POST /memory/confirm`：确认或忽略蒸馏记忆。

## 学习工作台与迁移

- `GET /workspace/metrics`：读取当前学习指标，并写入当天用户快照；响应同时包含近 30 天 `history`。
- `GET /workspace/metrics/history?days=30`：读取 7 至 365 天按用户隔离的指标趋势。
- `GET /workspace/outcomes?limit=50`：读取由真实测验得分和复习评分生成的学习效果事件；`metrics.learning_effect` 使用这些观测输出分数变化、保留率和复习间隔校准建议。
- 工作区 JSON/ZIP 导出和导入包含 `learning_outcomes`，迁移后保留校准历史；旧版不含该字段的导出仍可导入。
- `GET /workspace/export/archive`：导出关系数据、文档清单和受限原文件归档。
- `POST /workspace/import/archive`：校验 ZIP 路径、容量、清单和 SHA-256，恢复原文件并自动排队重建索引。
- `GET /notifications/stream`：任务通知 SSE；多实例可使用 Redis Pub/Sub，数据库事件表负责历史和断线补偿。

## 管理接口

- `GET /admin/secrets/internal-token`：管理员查看内部服务令牌指纹与轮换状态。
- `POST /admin/secrets/internal-token/rotate`：管理员先更新 Python 接受令牌，再无停机切换 Java 出站令牌；请求体为 `new_token`。

Python 内部接口 `POST /api/v1/agent/tools/{tool}/approve` 同时要求内部服务令牌与 `X-Admin-Api-Token`，为指定用户签发有时限的高风险工具审批令牌。工具执行仍会独立检查 scope、共享日配额和隔离级别；审批令牌不能替代这些检查。
