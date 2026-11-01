# 回答终态与重试隔离

Gateway 将证据核验后的正文、引用、`completed` 状态和错误清空写入同一条 MySQL UPDATE；事务提交成功后才向浏览器发送 `done`。上游连接可以继续保持打开，Gateway 不等待 EOF 才保存。正文为空、引用 JSON 无效、消息已删除或执行权过期时拒绝完成。未收到完整终态帧的 EOF 是失败。

每次回答带持久 `answer_generation`。V31 为历史记录填 0，新请求从 1 开始；失败或停止后的同 request_id 重试递增。成功及失败回调同时校验 generation 与 processing 状态；旧请求不能覆盖新尝试，迟到的失败不能撤销已完成答案。已完成请求重放正文和引用，不重新调用模型。通用 MyBatis 实体更新不允许改写这些受保护字段。

SSE 在完整事件帧边界解析，支持多行 data 并以单行 JSON 转发。成功前持久化失败返回通用 error；成功后浏览器关闭连接不回滚已提交结果。错误日志不写回答正文或模型密钥。

## 升级与回滚

1. 停止 Gateway、Python worker 和前端入口，保存一致的 MySQL 备份以及当前应用镜像标识。既有索引、辅助存储与数据卷按正常整站备份流程保留。
2. 运行带 V31 的 Gateway，Flyway 使用独立迁移账号。启动成功后再恢复其他服务，执行真实回答、立即断流、历史读回和重放验证。
3. 不同时运行新旧 Gateway。旧版本不校验 generation，混跑会破坏隔离。若需回滚，停写后恢复匹配的数据库快照和旧应用镜像；不要在线删除字段或修改 Flyway 历史。

## 验证与范围

`ChatAnswerTerminalTest` 在真实 MySQL 验证 V30→V31、原子保存与错误清空、坏 JSON 回滚、旧实体、重试隔离、终态竞争和消息删除。`ChatStreamTerminalTest` 使用真实 HTTP 上游验证无需 EOF、提交后才发送 done、持久化失败、断流、截断与多行 SSE。`answer-terminal-real.spec.js` 在真实站点的桌面与移动视口检查立即取消、立即读取历史、同步/流式重放、刷新及引用。

## 显式停止、断流与超时

Gateway 在连接模型服务前发送 `start`，包含 `session_id`、`request_id` 和正整数 `answer_generation`。浏览器只能使用本次握手代次调用认证后的 `POST /api/v1/chat/stop`；服务端锁定归属会话与助手消息，只把本代 `processing` 改为 `stopped / USER_STOPPED`。重复停止幂等，旧代次返回 409，其他用户不能操作。完成和停止并发时只有一个终态胜出，完成回执不能被前端改成停止。

前端先请求停止并确认回执，确认失败保留连接、提示重试；未收到握手时先记录停止意图。创建会话尚未返回时可本地取消，取消后不发送生成请求。意外 `AbortError` 不再自动当作用户停止。刷新历史后按持久错误码显示断流、超时、模型、核验或记忆失败原因；保留部分回答并提供重试，不回显内部异常。

每个活跃 Gateway 流每 500 ms 读取持久消息状态，不依赖进程内停止标记，故另一 Gateway 实例也可以确认停止。每秒 SSE 注释心跳检测浏览器断开；终止时取消尚无响应头的 HTTP future 或关闭已建立的响应体，随后保存当前代部分正文。普通断开记录 `failed / CLIENT_DISCONNECTED`，主动停止保留 `stopped`。无响应模型的 Gateway 总时限默认 180 秒，可用 `mneme.chat-stream-timeout-ms` 调整，超时记录 `MODEL_TIMEOUT`；连接建立上限 10 秒。单实例同时监视最多 64 条流，满额明确失败；每条流的定时任务与许可在终态释放。

心跳 socket 写入使用独立有界线程池，每流至多一个待执行心跳，慢客户端不能阻塞状态监视和取消。全部事件帧与心跳串行写入，避免并发交错破坏 SSE。MVC 异步上限比流监视上限多 30 秒，留出分类和持久化时间。Spring 7 默认提供不传播 flush 的输出包装，Controller 仅对 SSE 显式调用 servlet flushBuffer；代理为该路径关闭压缩，使用正值刷新间隔以保留客户端断开传播，不能使用会禁止上游取消的负值间隔。

Python 的模型 iterator 由 `closing_async_iterator` 显式关闭，ASGI 接收端并发监听 disconnect，即使上游没有下一个 Token 也可取消；模型、引用核验和记忆异常分别携带 `MODEL_ERROR`、`GROUNDING_FAILED`、`MEMORY_FAILED`。Python 既有单次 Token 超时仍提供带明确超时提示的原文降级回答，并记录 `model_timeout` 指标；这与 Gateway 等待上限触发的失败不同。

`ChatStreamCancellationTest` 使用真实 HTTP 验证无响应头停止、沉默响应体关闭、无输出超时、心跳检测断流及跨实例代次失效；MySQL 测试检查停止/完成竞争、幂等和旧代隔离。`chat-stop-real.spec.js` 通过真实网页、Gateway、MySQL 和 Python HTTP 连接检查桌面/移动端主动停止、无 Token 停止和页面刷新断开。测试模型仅对准确 QA 用户及会话替换，记录 iterator 关闭，finally 按字节恢复服务模块并删除临时控制文件；没有生产测试开关或任意模型 URL 旁路。

`ChatServletStreamingTest` 在真实 Spring MVC / Jetty socket 上要求模型未结束时 3 秒内收到握手和心跳，防止仅用内存 OutputStream 测试遗漏框架缓冲。真实浏览器回归要求 10 秒内收到 SSE 响应头、无压缩、部分正文实时可见，停止或刷新后 5 秒内观察到上游 iterator 关闭，并直接核查 MySQL 历史状态与错误分类。测试截图禁用有限入场动画，仅用于采集最终渲染状态。

这些是 P1-06/MN-007 的回答保存与停止子项。Gateway 的[候选入库已使用持久任务](PENDING_MEMORY_OUTBOX.md)，在答案事务中原子交接，后续入库失败不回滚答案。当前 Python 的同步 `complete_conversation` 仍在回答路径，[输入快照](MEMORY_INPUT_SNAPSHOT.md)尚不构成持久任务或整体幂等，完整记忆处理解耦仍待完成。停止不能撤销已发生的记忆副作用，同步记忆阶段的取消也仍受其阻塞调用约束。不能据此宣称完整 P1-06 已完成。
