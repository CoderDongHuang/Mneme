# 账号删除：会话清单及读回

对应原审查 P1-05 / MN-006 的 Redis、文件清理与失败重试子项。

Gateway 在 `session_cleanup` 阶段按用户从 MySQL `chat_session` 读取权威清单，以 ID 游标每批最多 1000 个发送到内部 Agent。MySQL 会话直到后续账号删除才级联移除；任一批失败或回执不可验证都保留本阶段及会话行，下一次从完整清单重试。不调用会自动裁剪 TTL 的界面列表来确定删除范围。

内部 `POST /api/v1/admin/user/{user_id}/session-cache` 接受 1–1000 个 ASCII 数字 ID，逐一清理短期和工作记忆、删除 Redis key，并以独立 `EXISTS` 读回。Gateway 严格验证 `status=verified`、整数 `checked_sessions=批次大小`、整数 `redis_sessions=0`；缺失值、布尔、字符串或浮点数都不当作成功。此接口依赖现有内部服务认证，只接受受信 Gateway 从用户归属查询得到的 ID；不对公网提供任意缓存清理能力。

随后 Agent 直接读取未裁剪的 JSON 清单，兼顾历史本地条目。文件不存在表示没有可选元数据；损坏、结构错误、权限拒绝则失败，不能当成空结果。所有缓存、Trace 和隐私清理及 Redis 最终读回成功后才移除清单，删除后检查文件路径确实不存在。这样失败后仍有本地重试范围。重复删除幂等，其他用户清单与缓存保持。

## 验证

- Python 故障测试覆盖过期和缺失条目、Redis 删除静默无效、读取失败、清理方法无效、损坏清单、权限错误、文件 unlink 静默无效、后续阶段失败和重试。
- 真实 MySQL/Flyway Saga 测试覆盖 2001 条分页及交错其他用户、错误回执、后批传输失败、可选元数据删除失败、保留用户和会话清单及恢复重试；既有 worker fencing 同时回归。
- `python-agent/scripts/verify_session_cleanup.py` 必须指向空的独立 Redis，通过真实 DEL/EXISTS 和文件验证故障阻断、保留清单、恢复重试、隔离及幂等。示例：从 python-agent 目录设置 `MNEME_SESSION_QA_REDIS_URL` 后运行该脚本。禁止使用应用 Redis；脚本拒绝非空实例。
- `frontend/e2e/session-cleanup-real.spec.js` 在真实 Gateway/MySQL/Redis 上创建两个独立 QA 用户，构造过期条目及缺失元数据的会话，提交账号删除并直接读回三个存储，实际网页仍能打开另一用户的会话；结束后核验两个 QA 账号清理。桌面和移动纳入全栈 CI。

## 升级与边界

Gateway 新增内部调用依赖新版 Agent；停写并备份匹配数据库、持久目录和旧镜像，一起升级，不混跑旧新版本。接口不引入新数据库迁移；回滚仍须按部署手册停写恢复匹配快照和旧容器，不能仅换镜像后继续写。

这不是完整账号擦除协议：在途模型/反思写入的防复活、跨实例进程缓存清理、其他存储的最终账号级核验及 SQLite WAL/备份的物理保留仍需后续独立完成。该项不证明物理不可恢复清除，不提前关闭整个 MN-006。
