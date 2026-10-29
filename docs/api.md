# 接口契约

浏览器通过前端同源反向代理访问 `/api/v1`；直接调试网关可使用 `http://localhost:8080/api/v1`。认证接口设置 `mneme_session` HttpOnly Cookie，浏览器请求携带 Cookie；非浏览器客户端也可使用：

```http
Authorization: Bearer <jwt>
```

Java 普通响应采用 `{ "code": 200, "message": "success", "data": ... }`。

## 认证

- `POST /auth/register`：`{ "username", "password" }`
- `POST /auth/login`：`{ "username", "password" }`
- `POST /auth/logout`：撤销当前服务端会话并清除 Cookie。
- `POST /auth/password-reset/request`：按用户名和绑定邮箱请求 15 分钟有效的验证码。
- `POST /auth/password-reset/confirm`：凭验证码设置新密码并撤销旧会话。

通过 HttpOnly Cookie 建立会话，响应体只返回 `userId` 和 `username`；JWT 不返回给 JavaScript。

## 会话

- `POST /sessions`：创建会话。
- `GET /sessions`：按更新时间倒序查询。
- `GET /sessions/{id}/messages`：读取消息。
- `DELETE /sessions/{id}`：删除会话及消息。

## 对话

- `POST /chat`：同步 JSON 回答。
- `POST /chat/stream`：SSE 流式回答。

请求字段：`session_id`、`message`、`knowledge_base_ids`；可选 `selected_document_ids`（最多 1000 个）、`tags`（最多 20 个，每个 1–80 字，AND 语义）、`date_from`/`date_to`（YYYY-MM-DD，1000–9998 年，按文档导入时间，结束日包含）。空文档选择表示不额外限制文档；无可访问匹配文档时严格返回空范围。`user_id` 和内部 `document_ids` 由网关计算，客户端提交内部字段不能绕过权限。日期起止颠倒或格式错误返回 400。

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

文档状态：`parsing -> ready | partial | failed`；删除时为 `deleting`，删除任务失败时为 `delete_failed`。`partial` 表示有可检索内容但部分页/能力不可用，应查看 `parseReport`，不能当成完整成功。报告含 parser_version、content_sha256、indexed_at、页/片段统计与逐页 warnings，不保证复杂版式解析正确。

来源额外返回 `retrieval_ranks`（召回通道到名次）、`content_sha256`、`indexed_at`、`parser_version`。排序分数不是答案可信概率；打开原文仍由网关校验权限和删除状态。资料 QA 在 token 展示前核验引用与声明，因此首 token 可能比闲聊慢；失败返回拒答正文。

## 供应商配置检测

`POST /health/providers/check` 必须登录，转发到 Python 内部保护接口。返回部署级 Chat/Embedding/Rerank/OCR 的脱敏 profile、状态、延迟与缓存信息（60 秒缓存），可能执行少量合成请求并产生费用。状态区分 missing_credentials、authentication_failed、quota_or_rate_limit、model_unsupported、timeout、runtime_missing、disabled、ok；不回传密钥，也不能代替业务验收。个人交互模型使用下列独立配置；共享索引和后台服务仍由部署方管理。

## 个人偏好与模型

- `GET/PUT /settings/preferences`：当前登录用户的 `language`（zh-CN/en）、IANA `timezone`、布尔 `notifications`、`theme`（system/light/dark）。
- `GET/PUT /settings/models`：`provider`（deepseek/dashscope/openai）、`model`、`enabled`、写入时的 `apiKey`。读取仅返回 `hasKey`/`keyMask`，不含密钥；同服务商密钥留空保留旧值，`clearKey=true` 显式清除。切换服务商不能沿用旧密钥。
- `POST /settings/models/test`：相同配置格式，实际调用模型但不保存；可能产生费用，返回模型及延迟。固定服务商地址不接受任意 URL。
- 模型配置 AES-GCM 加密并绑定用户 ID；只通过受内部令牌保护的请求上下文传入 Python，不放入全局共享模型客户端。账号删除级联清理设置。

## 学习交互补充

- `PATCH /sessions/{id}`：重命名当前用户会话；历史消息保留真实来源信息。
- 测验生成/列表响应隐藏答案与解释；`POST /workspace/quizzes/{id}/submit` 服务端评分后返回解释，支持 `request_id` 防止相同提交产生重复学习记录。
- `GET/PUT /workspace/quizzes/{id}/draft`：`answers` 数组与 `current_question`，仅本人题集可读写。
- `GET /workspace/quizzes/{id}/attempts`：已提交记录；`POST /workspace/quizzes/{id}/reports`：题目问题反馈。
- `PATCH /workspace/memories/{id}`：编辑/确认/归档等操作同步派生检索；不以不存在的置信度充当事实保证。

## 个人和整站恢复

- `POST /workspace/import/archive/preview`：multipart `archive` ZIP 与 `scope`（all/knowledge/conversations/learning），验证后返回 SHA-256、版本、时间、数量、缺失原文和同名资料库冲突。个人 ZIP 未加密。
- `POST /workspace/import/archive`：同一文件、scope 和预览的 `sha256`；新增副本，不覆盖现有数据，文件索引异步重建。旧客户端可省略摘要，仍执行完整归档校验。
- `GET /admin/recovery/site`：宿主机归档及任务历史；`POST .../preview`：`archive`；`POST .../jobs`：`action`（backup/restore）、`confirmation`（BACKUP SITE/RESTORE SITE），恢复另需归档名及预览摘要。
- 整站接口独立检查 active admin + `X-Admin-Token`；宿主机另验恢复令牌，网关不挂载 Docker socket。配置及真实恢复说明见 [宿主机恢复](HOST_RECOVERY.md)。现有 `/admin/recovery` GitHub 演练接口继续保留。

## 记忆

- `GET /memory`：读取画像。
- `POST /memory/write`：手动补充。
- `POST /memory/confirm`：确认或忽略蒸馏记忆。

## 学习工作台与迁移

- `GET /workspace/documents/{id}/tags` 与 `PUT /workspace/documents/{id}/tags`：读写当前用户文档标签，请求体为字符串数组；空数组清空。
- `GET /workspace/retrieval/debug?kbId=...&query=...&topK=...`：支持重复查询参数 `documentIds`/`tags` 及 `dateFrom`/`dateTo`，权限和筛选语义与聊天相同。
- `GET /workspace/documents/{id}/preview`、`GET /workspace/documents/{id}/file`、`GET /workspace/documents/{id}/pages/{page}`：可传 `sha256`（64 位十六进制）精确选择版本；页图为 PNG。无 hash 选择当前文件；未知版本返回 400。历史版本缺解析报告明确提示，不返回当前报告冒充历史。
- 解析报告的 `pages` 含文字层、页尺寸、文本、正文/表格块与 OCR 区域（坐标、文字、0–1 置信度），`chunks` 是有界摘要；达到体积预算标记 `preview_truncated`。复杂 OCR 结果需核对原图。
- `POST /workspace/tasks/{taskId}/cancel`：等待中或运行中入库任务协作取消；请求成功不等于已完成清理，轮询任务到 `cancelled`。`POST /workspace/tasks/{taskId}/retry` 重试取消任务返回新的 task_id；活动任务拒绝并发替换/重解析/删除/恢复。
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
