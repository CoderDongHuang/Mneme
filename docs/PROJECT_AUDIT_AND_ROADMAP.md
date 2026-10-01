# Mneme 项目审计与新路线图

> 重新审计日期：2026-09-27
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
| GitHub Actions | 通过 | Run `36318284964` 的 7 个必需作业全部成功，包含依赖哈希安装、供应链、Python、Java、前端、真实 OCR、Distributed 和 Full-stack 备份恢复验收 |

本地测试通过表示已覆盖路径没有发现回归，不表示外部模型、所有文档类型、生产代理拓扑和大规模并发均已得到证明。V14 Flyway 迁移、双节点 Trace、对象存储故障注入和备份恢复已由 GitHub Actions 的真实基础设施作业验证。

## 4. P2 修复结果

本轮七项 P2 均已实现并通过定向回归：

1. ✅ **聊天输入资源上限。** Java 与 Python 统一限制消息 8000 字符、会话 ID 128 字符、知识库 ID 最多 20 个且单个最多 128 字符；Python 端会去除 ID 两端空白并拒绝空值。
2. ✅ **Prometheus 路径基数治理。** Python HTTP 指标优先使用 Starlette 路由模板，未匹配请求统一归入 `unmatched`，不再使用含会话 ID、文档 ID或查询参数的原始路径。
3. ✅ **多节点反思调度。** 会话计数使用 Redis 原子 `INCR`，反思使用带过期时间的分布式租约；同一用户只由一个节点执行，失败释放租约保留计数，成功按认领数量递减，新增会话不会被覆盖。
4. ✅ **WebSocket 边界收敛。** 前端和 API 实际使用 SSE，已移除未使用的 Spring WebSocket 依赖、配置、握手鉴权器和进程内连接处理器，并更新相关架构文档。
5. ✅ **备份机密性与来源验证。** 新版本备份支持 AES-GCM 文件加密、HMAC-SHA256 manifest 签名、密钥版本和生产强制保护；恢复会验证签名、密文校验和及解密后的明文校验和，并兼容 v1 未保护归档。
6. ✅ **告警通知落地。** Alertmanager 已提供 webhook receiver、critical/warning 分级路由、critical 抑制 warning 和 resolved 通知；部署通过 `ALERTMANAGER_WEBHOOK_URL` 注入真实通知地址，并启用环境变量展开。
7. ✅ **Python 依赖可重现性。** 直接依赖已固定版本，维护带哈希的 `python-agent/requirements.lock`，Docker 与 CI 使用 `--require-hashes` 安装；Chroma 已升级到 `0.6.3`，三个无上游修复版本的漏洞仍保留有边界和到期日的例外。

## 5. 新的后续实施顺序

### 近期

1. ✅ 在 GitHub Actions 上确认本轮锁文件安装、Alertmanager 配置和备份保护在真实 Linux 环境验收。Run `36318284964` 的全部作业已通过。
2. ✅ 完成 Chroma 0.5.3 安全例外复核并升级到兼容的 `0.6.3`；同时修复 Chroma 0.6 集合名称 API 变化。OSV 确认修复版本尚未发布，例外继续由 CI 精确限定为三个编号并保留到期日。
3. ✅ 为输入拒绝率、Prometheus 标签数量和反思租约接管增加低基数指标、趋势报告和 CI artifact；Full-stack 与灾备工作流均采集 `operational-trends.json`。

### 中期

1. ✅ 已将反思执行迁移到 Redis Streams 共享可靠任务队列，consumer group 负责消费，`XAUTOCLAIM` 接管崩溃消费者的 pending 任务，Redis 租约继续防止同一用户重复执行。
2. ✅ 已加入 `scripts/alertmanager_drill.py`：灾备 CI 连接真实 Alertmanager API 验证 firing/resolved 与 silence API，另测 receiver 故障探测并输出 JSON 证据；本地 deterministic 模式会明确标出验证范围。
3. ✅ 已加入 `scripts/backup_key_rotation_drill.py`，验证 v1 旧密钥恢复、v2 新密钥归档、旧密钥退役拒绝和隔离目录跨环境恢复。

### 长期（2026-10-01 实现补齐）

1. ✅ **信封加密与异地恢复：实现、协议门禁和真实归档入口完成。** 备份使用随机 AES-GCM 数据密钥，由 `BACKUP_KMS_COMMAND` 包装/解包，签名 manifest 记录密钥版本和包装密钥；`scripts/backup_aws_kms.py` 提供 AWS KMS CLI 适配器。严格 AWS 模式验证 STS、S3 地域、公开访问阻断、桶策略、版本控制和 KMS 密钥状态，实际归档工作流按指定 S3 对象版本下载并校验非空归档，恢复时拒绝未签名或未加密归档。运行该工作流仍需要部署方配置真实 KMS/IAM/S3 凭据，这是现场验收前提而不是缺失的代码路径。
2. ✅ **真实领域质量与容量趋势：实现及两次独立运行的趋势验收完成。** `model-quality.yml` 比较同版本 RAG、测验和向量评测的前后运行，`capacity.yml` 读取前次容量报告并检查 p95、错误数、恢复时长；缺失指标、数据集不一致、质量门禁失败或没有历史均会失败，不再把 `insufficient_history` 当作成功。容量脚本含 Chroma/Redis 五组故障矩阵及三种数据规模；本轮真实模型趋势与两轮容量验收已通过，具体范围和运行编号见第 9 节。更长时间、生产规模的趋势仍由定时作业继续积累。
3. ✅ **基于使用数据的策略：测量、建议、账单对账和受保护生产入口完成。** LLM 调用预留估算成本，可通过 Redis 原子共享日预算拒绝超额请求，公开低基数成本指标；`scripts/usage_policy_report.py` 要求带时区的采集时间、正样本数、测量窗口和非空证据来源，并拒绝未来快照、不自动改动租户配置。新增 `.github/workflows/usage-policy-production.yml`，使用受保护 Environment、真实生产连接和精确区间账单导出，只有 `calibrated` 才通过，并保留不可覆盖的报告历史。现场运行仍需要部署方提供真实样本和账单，这是运行前提；测试夹具不会被标记为生产校准。

上述三项的部署验收边界继续适用；2026-10-01 已补齐的实现与本轮证据见第 9 节。2026-09-30 的 PR #9 已合并，Run `36727111494` 的 7 个作业全部通过，合并后的 main Run `36729205787` 也成功。历史成功记录不代表 2026-10-01 的代码已通过 CI。

## 6. 发布边界

下一次发布前必须满足：PR CI 全部通过；V14 在真实 MySQL 上迁移成功；安全扫描没有未解释的 high/critical；真实栈注册、上传、解析、检索、流式回答、登出、密码重置和账号删除流程通过；失败报告与测试 artifact 可追踪。

在生产代表性验证持续积累前，项目说明应继续使用“Beta”和“本地自托管”，不使用“生产级”“完全准确”或“支持任意复杂文档”。

## 7. 最新 CI 追踪

旧的通过记录不能代表当前提交状态。本轮提交 `d4f6a87` 对应的 GitHub Actions Run `36318284964` 已确认，结论为 `success`：

- `pip install --require-hashes -r python-agent/requirements.lock`、Python、前端、Java 和真实 OCR 作业通过。
- 供应链作业已通过，包含依赖安装、`pip-audit`、镜像漏洞扫描、密钥扫描和 SBOM 策略。
- Python、Java、前端、真实 OCR 和 Distributed 作业已通过。
- Full-stack 作业的完整栈启动、真实浏览器、跨存储删除和备份恢复演练全部通过。

上述两个依赖已升级到 `Pillow==12.3.0` 和 `onnxruntime==1.23.2`，并更新 Linux CPython 3.11 wheel 哈希；`uvloop==0.22.1` 已补齐版本和哈希并通过 `--require-hashes` 安装。Chroma Python 包和服务镜像现为 `0.6.3`，`chroma-hnswlib==0.7.6` 已补齐 Linux wheel 哈希。CI 使用固定版本 `rustfs/rustfs:1.0.0`。

### 本轮隐患核验

- ✅ `python-agent/requirements.lock` 的 `uvloop` 版本与哈希已核实，GitHub Actions 安装作业成功。
- ✅ 依赖审计范围已固定为带哈希锁文件，`pip-audit --requirement python-agent/requirements.lock` 已成功。
- ✅ 对象存储下载与启动：Run `36318284964` 的 RustFS 完整栈启动及浏览器、删除演练步骤成功。
- ✅ 备份恢复演练：Run `36318284964` 在宿主机安装锁定依赖后通过，恢复报告和 RPO/RTO 检查均通过。
- ✅ Full-stack 与全量 CI 验收：Run `36318284964` 的 7 个必需作业全部成功，本轮 P0/CI 验收完成。

## 8. 2026-09-30 本地复核

- 信封加密的 AWS CLI 适配器改用跨平台临时文件并在命令失败时清理；异地演练拒绝只配置部分远端步骤。测试覆盖命令接口、清理和配置拒绝，但没有真实 AWS KMS/S3 凭据，不能视为跨地域恢复验收。
- 趋势门禁拒绝非有限数值，避免 `NaN`/`Infinity` 绕过回归阈值。真实领域评测与容量趋势仍须积累同版本、同数据集的连续作业报告。
- 策略快照不把注册人数或进程启动以来的 Prometheus 累积序列当成窗口内使用样本；活跃会话以 `last_seen_at` 限定测量窗口。生产校准现在由受保护工作流执行并严格要求真实账单对账；学习效果仍是观察指标，不会被账单对账误称为因果验证。
- 本轮 Python 全量 205 通过、1 跳过，Ruff 通过；Java 全量 64 项通过（包含本机 Docker/MySQL 的 Testcontainers 迁移测试）；前端 13 项单测、lint、构建和 mock E2E 的 8 项通过，真实栈 E2E 的 2 项按配置跳过。`npm audit` 为 0 漏洞。`pip-audit` 仍报告 ChromaDB 的 3 个无修复版本的已知漏洞，适用范围和限制见 `docs/SECURITY_RESPONSE_POLICY.md`。PR #9 的 CI Run `36727111494` 已通过全部 7 个作业并合并，main Run `36729205787` 成功。

## 9. 2026-10-01 长期功能补齐

1. **信封加密与异地恢复。** 演练可输入实际归档，对复制、独立回读、下载后归档及所有恢复明文分别校验。严格 AWS 模式观察 STS、S3 地域、公有访问阻断、桶策略、版本控制和 KMS 密钥状态，固定观察到的密钥 ARN，显式拒绝本地密钥与自定义传输替代。新增 OIDC 云恢复工作流，支持指定 S3 对象版本的实际归档；报告区分真实归档与受控样本。恢复器拒绝非空目标、链接/Windows junction 祖先及 Windows 特殊归档路径。操作说明见 `docs/cloud-recovery.md`。
2. **真实领域质量与容量趋势。** 报告记录作业、分支、模型/负载配置及输入摘要，拒绝不可比历史、自我比较、非有限阈值和失败报告。工作流按分支寻找历史，首次仅能显式建立基线，仍记录 `insufficient_history`；第二次独立运行才判断趋势。容量覆盖两个 Agent、三个数据规模及五组 Redis/Chroma 故障，检查全部轮次、绝对恢复时限及负载持续时间；失败路径恢复已停止服务并输出失败证据。
3. **基于使用数据的策略。** 实际保留 Trace 占用与窗口活动分开测量，校验计数、配额、时间和数值；报告接收真实账单导出，检查生产来源、费用范围、UTC 费用区间、完整性和估算误差，并保存不可覆盖的报告历史。对账只代表该区间的费用一致性，不能证明学习效果或策略已验证。模型调用现在将预留的默认输出上限传给同步、异步和流式模型，拒绝异常预算/单价/计数。说明见 `docs/USAGE_POLICY.md`。

安全复核新增发现 `GHSA-42vr-xj54-vc7v`（PyJWT 2.14.0 深层 JSON 载荷异常），已升级到 `2.15.0`、核实官方 wheel 哈希并增加攻击载荷回归。复扫只剩已限定的三个 Chroma 无修复公告；前端依赖审计为 0 漏洞。

本轮本地验证：Python 全量 515 项通过、1 项跳过，Ruff 通过；Java 64 项通过、无跳过，包含真实 Docker/MySQL Testcontainers 与 V14 迁移；前端 lint、生产构建、13 项单测及 8 项 mock 浏览器测试通过，2 项真实栈用例按配置跳过。受控本地信封归档恢复通过全部明文摘要校验，报告明确记录 `cloud_verified=false`。工作流 YAML 与 Git 空白检查通过。

云端复核额外发现并修复 Jackson `CVE-2026-91776` / `CVE-2026-91777`，BOM 升级到 `2.21.7`。首次容量运行的五组恢复成功，但默认 IP 限流拒绝 315 个负载请求，因此该运行不能作为通过基线。容量环境显式配置每 Agent 每来源 IP 10 次/秒、突发 60 次；生产默认仍为 1 次/秒、突发 60 次，通过 `INTERNAL_RATE_LIMIT_PER_SECOND` / `INTERNAL_RATE_LIMIT_BURST` 配置且必须为有限正数。查询使用有界线程池避免阻塞事件循环，负载按请求均匀发送，总计 600 次、120 秒、最多 24 并发，维持零错误、p95 2000ms 和恢复 240 秒门禁；这不是默认部署限流或高突发容量承诺。

提交 `8293e2b23c62a9e2b504f12a6432346576d7d70c` 的可追踪云端证据：

- [CI Run 36849723516](https://github.com/CoderDongHuang/Mneme/actions/runs/36849723516)：全部 7 个作业通过，包括供应链、真实 OCR、分布式验收、真实浏览器、使用快照采集、跨存储删除和备份恢复。Python/Java 运行镜像扫描没有 High/Critical，密钥扫描通过；三个无修复 Chroma 公告仍按安全策略精确限定。
- [真实模型 Run 36849903404](https://github.com/CoderDongHuang/Mneme/actions/runs/36849903404)：OCR、多模态、RAG、测验及真实向量质量门禁通过；RAG/测验/向量趋势各比较两份可比独立报告，均为 `passed`。先前 Run `36844854212` 的三份质量报告通过，失败仅在旧历史发现步骤，因此可用于质量比较；新 REST 历史发现已实际验收。
- [容量基线 Run 36849864185](https://github.com/CoderDongHuang/Mneme/actions/runs/36849864185)：600/600 请求、120 秒、零错误、p95 111.09ms，五组故障最长恢复 2.81 秒。首次显式建基线，趋势保持 `insufficient_history`。
- [独立容量趋势 Run 36851102456](https://github.com/CoderDongHuang/Mneme/actions/runs/36851102456)：相同配置下 600/600 请求、120 秒、零错误、p95 177.39ms，五组故障最长恢复 3.14 秒。趋势为 `passed`，p95 增量 66.30ms、最长恢复增量 0.33 秒，均未超过原门禁；两轮使用不同运行及种子标识。

以上容量证据覆盖本轮 CI 拓扑的检索负载与故障恢复，不代表生产吞吐上限。最终文档提交沿用相同模型/容量输入摘要，合并前仍核验该提交的完整 PR CI。

部署验收仍有外部前提：仓库已配置真实模型密钥，但未配置 AWS 恢复角色、地域、桶和签名密钥；未提供生产使用快照及真实账单。本轮不会把本地 AWS mock 或账单测试夹具当作生产验收。
