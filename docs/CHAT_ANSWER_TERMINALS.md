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

这是 P1-06/MN-007 的回答保存子项。当前 Python 的 `complete_conversation` 和 Gateway 候选记忆保存仍在回答路径；持久记忆任务解耦、显式停止与断网语义分类继续单独实现，不能据本项宣称完整 P1-06 已完成。
