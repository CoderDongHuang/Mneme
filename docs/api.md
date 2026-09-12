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

文档状态：`parsing -> ready | failed`；删除时为 `deleting`，删除任务失败时为 `delete_failed`。

## 记忆

- `GET /memory`：读取画像。
- `POST /memory/write`：手动补充。
- `POST /memory/confirm`：确认或忽略蒸馏记忆。
