# 反思计数的持久投递回执

对应 P1-06 / MN-007 的安全重试前置条件。本项补齐反思计数的持久去重，不把仍同步执行的完整记忆提取、蒸馏与摘要处理标记为后台解耦完成。

## 身份与交接协议

`prepare_conversation` 在模型调用前固定 `delivery_id`。完成阶段按用户、会话及该 ID 记录一次反思计数，不依赖回答正文、时间或工作器身份。Gateway 请求已有稳定 request_id；没有 request_id 的直接调用，在 prepare 或旧调用的 state 中生成并保留随机 ID。同一个没有请求 ID 的新 HTTP 请求无法识别为旧请求，不能承诺跨请求去重。

复用 `knowledge_index_state` 的短用户事务：先检查账号、会话永久删除围栏，再验证并查询 `reflection_deliveries` 账本。账本使用会话 SHA-256 分桶，投递键为规范 JSON `[session_id, delivery_id]` 的 SHA-256，不保存正文或原始会话/请求 ID。结构损坏明确失败，不当空账本继续计数。已存在 SQL 回执只读取当前 Redis 计数；计数已消费时返回零，不重建计数。

新投递先由 Redis Lua 原子递增并写交接标记，再提交 SQL 回执，成功提交后才删除 Redis 标记。交接标记不设 TTL，旧版尚未过期的标记在重试时执行 PERSIST；因此 SQL 回滚、计数已消费或跨进程重放不会因标记七天到期而重新递增。计数自身仍默认保留七天，修复旧无 TTL 计数，重试不延长已有期限。SQL 已提交后的标记 DEL 故障仅记录固定诊断，保留已成功回执；后续重放或账号删除可重试清理。

没有两种身份的兼容调用仍将每次调用计为不同事件；只传一半身份在访问存储前拒绝。SQL 事务只覆盖短同步存储操作，不跨模型调用或 await。SQL 或 Redis 失败不回退本地，也不报告尚未提交的回执成功。SQLite 用于单主机；多副本需共享 MySQL 和 Redis，使用一致状态库配置。

## 删除与留存

回执保留到会话或账号删除，不能在后台任务仍可能重试时按七天清除。单会话删除在同一 SQL 事务写永久 tombstone 并移除对应回执桶；即使账本外层损坏，仍先提交 tombstone 再报告清理错误。账号删除先提交永久 tombstone 并删除全部回执，再执行可失败、可重试的 Redis/Stream 清理，已删范围拒绝迟到投递。另一用户和另一会话不受影响。

升级前已经过期的 Redis 标记没有可追溯的 SQL 回执，不能重建历史去重记录。SQL 未提交且不再重试的交接标记可能持续保留，账号删除会按精确用户范围清理；自动孤儿留存治理仍归 P2-12 后续验收。本项不声称 SQL 与 Redis 为 ACID，不将 AOF everysec 的断电 RPO 承诺为零丢失，也不承诺回退不匹配数据库后的去重。

## 验证

- 单元测试覆盖 SQL 提交回滚、消费后重放、跨实例且 Redis 标记缺失、旧标记升级、标记清理失败及日志隐私、五类畸形回执、会话/账号删除和另一范围隔离。
- `python scripts/check_reflection_delivery.py` 在 SQLite、MySQL 两种配置下使用真实 Redis/SQL：八线程跨实例投递 32 次、消费后新解释器重放、实际 SQL 事务回滚、旧 TTL 修复、坏账本拒绝及删除围栏，最后删除合成数据。
- `python scripts/check_reflection_cleanup.py` 验证真实分页键、Stream/Pending 清理与失败重试，同时独立检查已删账号 SQL 回执为零、另一用户回执保留。
- `python scripts/verify_redis_durability.py` 在有/无密码隔离 Redis 上等待 fsync 后 SIGKILL，恢复 pending 任务再重放；两阶段挂同一独立 SQL 卷，结束清理该卷。
- 真实 localhost 桌面/手机聊天回归在正式 complete 后用独立进程读取 SQL 摘要回执，确认 Redis 交接标记已清。账号清理测试同时播种升级前旧标记，精确核验五个 Redis 键、SQL 回执、队列/Pending 删除为零；不放宽原断言。模型输出及指定写故障使用隔离 QA 夹具，其余 Gateway/Agent/存储走真实路径，不冒充外部供应商网络故障。

## 升级和回退

无新依赖、配置项或数据库结构迁移，但用户状态增加持久回执协议。停止全部旧应用写入者，保存匹配 SQL、Agent 数据、Redis AOF/RDB、镜像和配置后再替换，不能混跑不认识回执的旧工作器。回退必须先停写并恢复上述匹配快照，再启动匹配旧镜像；仅回退镜像可能重复计数。任务所有权规则仍见 [反思队列协议](REFLECTION_TASK_OWNERSHIP.md)。本项不关闭完整 P1-06、MN-007 或 P2-12。最终测试、实际截图和独立 PR 结果见 [整改记录](CODE_REVIEW_REMEDIATION_20261031.md)。
