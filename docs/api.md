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
- `DELETE /sessions/{id}`：隔离归属会话并持久化清理任务，返回 `{accepted: true, task_id, status}`，不代表清理已完成。相同请求返回同一任务回执；在任务中心查看 `session_delete` 终态并重试失败。Agent 缓存核验和 SQL 消息、待确认记忆清理全部通过后任务才为 `completed`，详见 [单会话删除](DELETION_PROTOCOLS.md#single-session-deletion-fence)。

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
- `GET /workspace/memories`：返回 `{memories: [...]}` 记忆列表。
- `PATCH /workspace/memories/{id}`：返回 `{status: "updated", memory: {...}}`，包含已保存记录。
- `POST /workspace/memories/{id}/restore`：返回 `{status: "restored", version, memory: {...}}`。
- `DELETE /workspace/memories/{id}`：返回 `{status: "deleted", id}`。

以上写接口直接返回 Agent 的提交回执，不依赖提交后的列表刷新；前端按记录 ID 更新或移除对应条目，版本读取失败单独提示。用户归属由 Gateway 的认证上下文覆盖，客户端提供的 `user_id` 不生效。Agent 内部按来源 IP 为推理、交互服务、固定清理/核验路由分别保留限流预算，每类均遵守配置限额，用户 ID 和请求头不能扩张预算。

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

<a id="citation-contract"></a>
## 跨端引用契约

`python-agent/app/models/chat.py` 的 Source 为同步与 SSE 引用模型，通过同一 citation_sources 边界生成。运行 `python python-agent/scripts/export_chat_contract.py` 导出 schema、示例和前端类型；加 `--check` 检测漂移，不手改生成文件。Python、Java、浏览器共同消费示例，检查空值、字段完整性和逐字节帧。
坐标为 [left, top, right, bottom] 四个 0–1 有限数，顺序有效，否则降为 null，保留正文和其他来源字段。兼容旧 CSV 坐标；空片段不改变引用编号。`citation-contract-real.spec.js` 验证真实 PDF、持久引用、重放及旧坐标，故障注入仅限该测试账号。

<a id="stream-contract"></a>
## SSE 契约维护

规范来自 `python-agent/app/models/chat_stream.py`。用锁定的 Python 3.11 / Pydantic 环境运行 `python python-agent/scripts/export_stream_contract.py`（或 `--check`），生成 contracts schema、Java classpath 副本与前端类型。新增 schema 约束必须先更新各端有界验证器及跨语言用例，不手改生成文件。
公开事件为 start/meta/token/memory/done/error/stopped；Agent 只发送 meta/token/memory/done/error，执行权和停止回执由 Gateway 产生。成功 done 必须带非负答案长度或 ok:true。引用页码/排名满足 Java 32 位整数范围，generation/长度满足 JS 安全整数；1.0 可作整数，布尔和数字字符串不可以。
Agent 序列化前、Gateway 累积/保存/转发前、浏览器回调前均验证。未知事件、坏 JSON、无效 payload 不得忽略后又判成功；固定 INVALID_CHAT_EVENT 不带原 payload/解析异常。Gateway 保存合法部分及失败状态并关闭上游；浏览器取消并释放 reader。持久化后 done、代次围栏及主动停止仍独立验证。
跨端用例 `contracts/chat-stream.cases.json` 必须按原始 JSON 读取，保留自有 __proto__ 键。真实 `chat-contract-real.spec.js` 需要真实 E2E 和显式故障开关，限定合成账号，finally 恢复模块原字节并删账号，日志不得含私密 canary。前端构建上下文需包含 contracts。三端匹配部署，停旧写入者；回退恢复匹配数据、镜像和配置。
**2026-11-03：PR #99 已合并，桌面和手机真实回归均通过。** 以上仅是 SSE/引用契约；其他 REST 契约、完整记忆解耦和物理留存仍未完成。

<a id="upload-cancellation"></a>
## 上传取消与回执

每次上传使用独立 UUID 与 AbortController，回执、文档、版本、解析任务在同一事务提交，提交/取消共用用户行锁。取消先取得锁会持久化 cancelled，拒绝迟到上传；提交先完成则返回 submitted 及文档/任务，后续到任务中心取消解析。响应丢失以同一编号核实，核实失败显示待确认，不自动重传。同编号重放返回原文档，主动重试用新编号；账号及原知识库范围不可变。
切库不改变批次目标；离页或换账号取消等待项，已发请求仍属旧账号，不向新页面回调。刷新后未决项显示待确认，核实可确认提交或建立取消回执。Servlet 清理 multipart 临时文件，复制/事务失败清除部分业务文件；已提交文件不因断网删除。
回执不含正文/文件名，随账号级联删除；已取消编号不能复用。代理必须允许独立取消请求，旧无编号客户端不支持本协议。验证迟到请求、并发/事务失败、租户隔离、真实限速中止与响应丢失后的读回。
