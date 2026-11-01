# 候选记忆持久化任务

对应 2026-10-30 审查 P1-06 / MN-007 的 Gateway 候选入库部分。Python 的提取、蒸馏、摘要和反思交接仍需后续独立改造，本项不代表整个 MN-007 已完成。

## 回答与候选的提交边界

Gateway 在同一 MySQL 事务中，将带执行代的回答从 processing 更新为 completed，并将候选列表写入 processing_task 的 memory_candidates 任务。交接失败时整个事务回滚，不向浏览器发送 done 或 queued。没有候选时不创建空任务。

提交后同步响应返回 memory_status=queued、空 pending_memories；SSE 发送 pending 为空、status=queued 的 memory 事件，再发送 done。未入库候选不会暴露确认按钮。提交后的浏览器断开不能将回答改回 failed。

后台工作器沿用 owner/lease/fence 和有限重试，在单一受租约保护的 SQL 事务中校验账号 active、回答 completed 和归属，写入全部候选、清空任务 payload 并完成任务。任何一步失败均回滚；重试不修改已经确认/忽略的同源候选，不接受其他用户或其他回答的 ID 冲突。错误提示、通知和日志不回传候选正文或数据库异常细节。

失去租约的工作器不能继续写入。账号删除状态取消候选写入并清空载荷；会话删除移除对应任务，迟到工作器不能复活任务。删除前已经提交的候选保留既有来源外键 SET NULL 行为。任务页标明“来源回答”，提供保存失败的独立重试，不使用文档解析修复指引，也不能因数字 ID 相同修改无关文档。

## 验证方式

- PendingMemoryOutboxTest 使用真实 MySQL、Flyway、MyBatis 和 Spring 事务，覆盖交接回滚、批次原子性、完成失败后的接管、账号/会话删除、并发删除及不同聚合 ID 隔离。
- ChatServiceTest、ChatStreamTerminalTest 检查同步和 SSE 的交接顺序、交接失败及下游断开；前端检查独立队列提示和任务来源/错误/重试。
- memory-outbox-real.spec.js 对唯一 QA 用户注入 pending_memory INSERT 故障，使用实际网页、Gateway、MySQL 和任务工作器验证回答完成、三次失败、真实重启、手动重试、载荷清空、幂等重放及实际确认记忆。桌面与移动均运行，检查横向溢出并保留视口截图。

真实测试中的模型与 complete_conversation 结果由仅匹配 QA 用户/会话的夹具提供，测试结束恢复 Agent 原文件并重启、移除触发器和账号。因此该用例验证 Gateway 候选交接及下游真实确认，不冒充 Python 记忆提取失败已解耦的证据。生产代码不包含测试故障开关。

## 升级和回退

没有新增数据库迁移，复用 processing_task。升级前保留匹配数据库快照、镜像和部署配置；本机使用忽略目录 artifacts 保存 SQL 和原容器，不能提交其中的私密环境文件。

先停止接受新回答并等待在途请求结束，再停写和备份，升级 Gateway 与前端后检查健康及真实任务。回退前先用新工作器处理完 memory_candidates 的 pending/retry/processing 任务；failed 必须处理或明确保留在匹配快照中。旧工作器不认识新增类型，不能直接对仍有未处理候选任务的数据库启动旧 Gateway。需要立即回退时，停写后恢复对应版本的数据库及原镜像/配置，使用成对备份，不能只换镜像。不得为让旧工作器启动而直接删除未保存的候选载荷。

成功和取消后 payload 清空；失败载荷为恢复保留。历史任务和其他存储的统一保留清理仍属于 P2-12。
