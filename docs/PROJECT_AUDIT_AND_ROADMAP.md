# Mneme 项目审计与新路线图

> 重新审计日期：2026-09-23
> 审计基线：`main` 分支
> 当前定位：个人与小规模团队本地自托管的 Beta 学习助手

## 1. 当前结论

上一版路线图中的历史阶段记录已经清空。本文件只保留 2026-09-22 重新审计发现的问题、本轮修复结果、实际测试证据和下一阶段计划。

Mneme 的认证、资料库、异步解析、RAG、流式对话、引用、记忆、学习计划、复习、测验、导入导出和自托管部署均有真实实现。本轮重新审计发现的 P1 安全性与一致性问题已经修复并通过本地自动化测试；当前没有已知 P0 或 P1 遗留。

项目仍定位为 Beta。外部模型质量、真实生产流量、不同代理拓扑和长期灾备效果不能由一次验收完全证明；本机因 Docker 不可用而跳过的 MySQL/Testcontainers 路径已由 GitHub Actions 的真实基础设施作业补充验证。

## 2. P1 修复结果

### ✅ 已完成：聊天幂等与会话隔离

- 聊天消息唯一键从全局 `(request_id, role)` 改为 `(session_id, request_id, role)`，不同会话可以安全使用相同请求 ID。
- 同一会话的请求准备过程使用数据库行锁，并在单个事务内创建用户消息和助手占位消息。
- 已完成请求直接回放持久化答案，不再调用 Python Agent；流式回放会发送 `token` 和 `done` 事件。
- 处理中请求返回 HTTP 409，失败请求可以使用同一请求 ID 重试。
- 相同请求 ID 携带不同消息内容时返回 400，避免错误复用。
- `request_id` 最大长度与数据库字段一致为 64；旧客户端未提供时由 Gateway 生成 UUID。

### ✅ 已完成：密码重置令牌原子消费

- 重置令牌通过带 `used_at IS NULL` 和有效期条件的原子更新抢占。
- 并发请求只有一个能够修改密码；抢占失败不会更新用户密码。
- 令牌消费、密码更新和会话撤销处于同一事务中，任一步失败都会回滚。

### ✅ 已完成：可信代理限流

- 默认不信任 `X-Forwarded-For`，直连请求只能使用连接端 IP。
- 仅当连接端命中配置的可信 IPv4/IPv6 地址或 CIDR 时解析转发链。
- 转发链从右向左剥离可信代理，非法地址或非法链会回退到连接端 IP。
- Compose 的 Gateway 端口仅绑定 `127.0.0.1`，并提供 `TRUSTED_PROXIES` 配置。

### ✅ 已完成：账号删除原子入队

- 入队过程增加事务并锁定用户行，用户冻结和删除任务创建不再分离提交。
- 每个用户只允许存在一个删除任务，服务层复用已有任务，数据库唯一索引提供最终约束。
- 并发请求不会重复创建任务，也不会留下“用户已冻结但任务未创建”的中间状态。

### ✅ 已完成：服务端会话寿命与撤销

- 新增服务端 `auth_session`，JWT 包含会话 ID，每次鉴权同时检查会话是否有效。
- 普通会话使用 `JWT_EXPIRATION`；“记住我”使用 `JWT_REMEMBER_EXPIRATION`，默认 30 天，Cookie 与 JWT 生命周期一致。
- Logout 会撤销当前服务端会话，而不只是删除浏览器 Cookie。
- 修改密码和重置密码会撤销该用户的全部现有会话。
- 迁移后不含会话 ID 的旧 JWT 会失效，用户需要重新登录。

## 3. 本轮验证

| 检查 | 结果 | 说明 |
|---|---|---|
| Java 定向回归 | 通过 | 23 项，覆盖本轮五类 P1 与请求兼容性 |
| Java Maven 全量 | 通过 | 64 项，0 失败，6 项 Testcontainers 因本机 Docker 不可用而跳过 |
| Python Ruff | 通过 | 全量静态检查 |
| Python Pytest | 通过 | 167 项通过，1 项跳过 |
| 前端 ESLint | 通过 | 全量检查 |
| 前端 Vitest | 通过 | 13 项通过 |
| 前端 Vite Build | 通过 | 生产构建成功 |
| Playwright mock E2E | 通过 | 8 项通过；2 项真实栈用例按配置跳过 |
| Docker Compose | 通过 | 基础、selfhost、production 和 security profile 均可解析 |
| npm audit | 通过 | 0 vulnerabilities |
| Git diff 检查 | 通过 | 无空白错误 |
| GitHub Actions | 通过 | 运行 `35703983277` 的 7 个作业全部成功 |

本地测试通过表示已覆盖路径没有发现回归，不表示外部模型、所有文档类型、生产代理拓扑和大规模并发均已得到证明。V14 Flyway 迁移、真实基础设施、跨存储删除、备份恢复和双节点 Trace 已由 [GitHub Actions #35703983277](https://github.com/CoderDongHuang/Mneme/actions/runs/35703983277) 验证通过。

## 4. P2 修复结果

本轮七项 P2 均已实现并通过定向回归：

1. ✅ **聊天输入资源上限。** Java 与 Python 统一限制消息 8000 字符、会话 ID 128 字符、知识库 ID 最多 20 个且单个最多 128 字符；Python 端会去除 ID 两端空白并拒绝空值。
2. ✅ **Prometheus 路径基数治理。** Python HTTP 指标优先使用 Starlette 路由模板，未匹配请求统一归入 `unmatched`，不再使用含会话 ID、文档 ID或查询参数的原始路径。
3. ✅ **多节点反思调度。** 会话计数使用 Redis 原子 `INCR`，反思使用带过期时间的分布式租约；同一用户只由一个节点执行，失败释放租约保留计数，成功按认领数量递减，新增会话不会被覆盖。
4. ✅ **WebSocket 边界收敛。** 前端和 API 实际使用 SSE，已移除未使用的 Spring WebSocket 依赖、配置、握手鉴权器和进程内连接处理器，并更新相关架构文档。
5. ✅ **备份机密性与来源验证。** 新版本备份支持 AES-GCM 文件加密、HMAC-SHA256 manifest 签名、密钥版本和生产强制保护；恢复会验证签名、密文校验和及解密后的明文校验和，并兼容 v1 未保护归档。
6. ✅ **告警通知落地。** Alertmanager 已提供 webhook receiver、critical/warning 分级路由、critical 抑制 warning 和 resolved 通知；部署通过 `ALERTMANAGER_WEBHOOK_URL` 注入真实通知地址，并启用环境变量展开。
7. ✅ **Python 依赖可重现性。** 直接依赖已固定版本，维护带哈希的 `python-agent/requirements.lock`，Docker 与 CI 使用 `--require-hashes` 安装；Chroma 0.5.3 的例外仍保留并要求在 2026-10-18 前复核。

## 5. 新的后续实施顺序

### 近期

1. 在 GitHub Actions 上确认本轮锁文件安装、Alertmanager 配置和备份保护在真实 Linux 环境验收。
2. 在 2026-10-18 前完成 Chroma 0.5.3 安全例外复核，优先升级到兼容且无例外的版本。
3. 为输入拒绝率、Prometheus 标签数量和反思租约接管增加持续趋势报告。

### 中期

1. 将反思执行从线程池迁移到共享可靠任务队列，保留 Redis 租约作为过渡和故障接管机制。
2. 为 Alertmanager 执行真实通知渠道的静默、抑制、升级和 receiver 故障演练，并将结果作为发布 artifact。
3. 为备份密钥轮换、旧密钥恢复和跨环境恢复建立自动化演练。

### 长期

1. 将当前 AES-GCM 文件加密升级为 KMS/Secret Manager 管理的信封加密，完成异地恢复验证。
2. 持续扩展真实领域评测、长时容量测试和多故障组合演练，使用趋势而不是单次结果决定发布。
3. 根据真实使用数据优化会话保留策略、模型成本预算、知识库容量和学习效果校准。

## 6. 发布边界

下一次发布前必须满足：PR CI 全部通过；V14 在真实 MySQL 上迁移成功；安全扫描没有未解释的 high/critical；真实栈注册、上传、解析、检索、流式回答、登出、密码重置和账号删除流程通过；失败报告与测试 artifact 可追踪。

在生产代表性验证持续积累前，项目说明应继续使用“Beta”和“本地自托管”，不使用“生产级”“完全准确”或“支持任意复杂文档”。

## 7. 最新 CI 追踪

旧的通过记录不能代表当前提交状态。提交 `0ea7339` 对应的 GitHub Actions Run `36239564024` 已确认：

- `pip install --require-hashes -r python-agent/requirements.lock`、Python、前端、Java 和真实 OCR 作业通过。
- 供应链作业已通过，包含依赖安装、`pip-audit`、镜像漏洞扫描、密钥扫描和 SBOM 策略。
- Python、Java、前端、真实 OCR 和 Distributed 作业已通过。
- Full-stack 作业因 CI 覆盖层使用的 Quay MinIO 镜像返回 `unauthorized`，在完整栈启动前失败。

上述两个依赖已升级到 `Pillow==12.3.0` 和 `onnxruntime==1.23.2`，并更新 Linux CPython 3.11 wheel 哈希。本次又将 CI MinIO 镜像切换为已验证可下载的固定 Docker Hub tag `minio/minio:RELEASE.2025-04-22T22-12-26Z`；在新的 GitHub Actions Run 明确成功前，本项目不能标记为 CI 全部通过。
