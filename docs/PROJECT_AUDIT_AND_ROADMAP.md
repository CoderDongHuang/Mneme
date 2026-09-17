# Mneme 当前项目审计与路线图

> 审计日期：2026-09-17
> 审计范围：`main` 分支源码、自动化测试、Compose 配置、运维脚本与文档
> 项目定位：个人与小规模团队本地自托管的 Beta 学习助手

## 1. 当前结论

Mneme 的核心产品闭环已经存在：认证、资料库、异步解析、结构化 RAG、流式对话、引用、三级记忆、学习计划、复习、测验、导入导出和自托管配置均有真实实现，不是仅有页面或占位接口。

旧版文档中的历史修复记录已经删除；本次完成的 P0 保留勾选项和可追踪验收链接，未完成工作继续按 P1、P2 和近期、中期、长期列出。

当前仍不能把项目描述为“全部功能均经过生产验证”。常规 CI 已执行真实基础设施上的全链路、跨存储删除故障注入和备份恢复演练，但模型生成与 Embedding 使用可重复的确定性 CI 替身；外部付费模型质量、Tesseract OCR、多节点对象存储/向量分片压测仍未进入常规验收。当前版本继续定位为 Beta。

本次复审除账号删除残留风险外，还发现并修复了 Chroma 冷启动依赖竞态、向量数据未真实持久化、非 root 日志权限、MinIO `.object-cache` 删除残留和并发创建会话分支死锁。对应用户隔离、失败传播、跨存储残留、恢复后 RAG 和 MySQL 并发测试均已加入自动化验收。

## 2. 重新验证结果

| 检查 | 结果 | 验证边界 |
|---|---|---|
| Python Ruff | 通过 | 全量 `app`、`tests` 静态检查 |
| Python Pytest | 106 passed，1 skipped | 跳过项依赖本机 Tesseract；包含可信删除、备份归档安全和确定性模型回归测试 |
| Java Maven Test | 39/39 passed | 本机 Docker 不可用时跳过 4 个 Testcontainers 测试；GitHub CI 在 Docker/MySQL 环境执行全部 39 个测试 |
| 前端 ESLint / Vitest | 通过，3 passed | Vitest 目前只有 API 客户端基础契约 |
| Playwright mock E2E | 8 passed，2 skipped | 桌面和移动端通过；2 个真实栈用例默认跳过 |
| Full-stack P0 acceptance | 通过 | CI 启动 MySQL、Redis、Chroma、MinIO、Python、Java 和前端，执行真实浏览器流程、删除故障注入与备份恢复 |
| Vite Build | 通过 | 生产构建成功 |
| npm 安全审计 | 通过 | 0 low、0 moderate、0 high、0 critical |
| Docker Compose | 通过 | 基础、selfhost 和 `security` profile 均可解析 |
| 离线 RAG | 110 cases | `Recall@5=1.0`、`MRR=0.8943`、`faithfulness_proxy=0.8762`、`citation_recall=1.0`、P95 `20.15ms` |

自动化测试通过表示已覆盖路径没有发现回归，不等于外部模型、不同文档领域和生产部署条件均已验证。

## 3. 已确认的实现范围

- Java 从 JWT 注入用户身份，Python 业务接口受内部服务令牌保护；密码、重置令牌、管理员接口和上传边界有安全测试。
- 文档支持 PDF、DOCX、PPTX、XLSX/XLSM、CSV、Markdown、TXT 和 HTML；具备版本替换、恢复、删除、解析报告、受限归档导入和索引重建。
- 检索包含 Dense、SQLite FTS5、RRF、查询改写、去重、上下文预算和可选重排器；引用保存文档、页码、区域及 OCR 元数据。
- 工作记忆、Redis 短期记忆和 Chroma 长期记忆已接通；长期记忆支持确认、冻结、来源证据、版本和回滚。
- 学习计划、复习卡、测验、错题转卡、薄弱点、会话分支、每日指标快照和趋势 API 使用真实数据库。
- 通知历史、Redis Pub/Sub、数据库轮询补偿、任务重试、废弃锁恢复、操作日志、Prometheus 指标和健康检查已实现。
- 本地/S3-MinIO 存储驱动、租户路径和配额、稳定向量分片路由已实现，但分布式部署效果尚未完成真实环境验收。

## 4. 当前问题

### P0：已完成（2026-09-17）

- [x] **全链路进入常规验收。** PR CI 在真实 MySQL、Redis、Chroma、MinIO、Java、Python 和前端上执行注册、上传、解析、RAG、回答、引用定位、多轮会话和刷新后持久化，并上传 Playwright 报告与截图。模型和 Embedding 使用确定性 CI 替身，外部模型质量仍属 P1/人工或定时验收。
- [x] **可信删除具备跨存储 E2E。** 自动化场景验证 MySQL、Redis、Chroma、MinIO、本地文件、SQLite 版本与 Agent 轨迹无残留，并覆盖 Chroma、MinIO、Redis 中断重试和 Java 重启后的最终一致性。
- [x] **备份恢复闭环完成。** 统一 Python 实现备份与恢复 MySQL、文件、头像、Chroma、MinIO 和 Python 辅助状态；使用环境凭据、版本化 manifest、SHA-256、归档路径安全校验，包含篡改/缺项回归测试、自动恢复后 RAG 验证及 RPO/RTO 报告。

验收证据：[GitHub Actions #35203480246](https://github.com/CoderDongHuang/Mneme/actions/runs/35203480246)，四个作业全部通过；`Full-stack P0 acceptance` 中真实浏览器、删除故障注入和备份恢复三个阶段均通过。

### P1：质量与可靠性

1. **RAG CI 不是质量门禁。** `evaluate_rag.py` 只输出指标，没有阈值失败逻辑。当前 `citation_precision=0.1909` 统计的是 Top-5 候选片段，与夹具中的最终引用目标 `0.80` 口径不一致；Top-1 实验为 `precision=0.7909`、`recall=0.8286`。需要改为评估最终引用选择，并为 Recall、MRR、Faithfulness、Citation Precision/Recall、拒答和延迟设置可执行阈值。
2. **OCR 和多模态仍缺真实质量验收。** 本机与 CI 未安装完整 Tesseract 语言包，真实视觉模型也未运行；现有夹具主要证明数据结构和降级路径，不证明扫描页、公式和图表理解准确率。
3. **水平扩展只有实现，没有部署证据。** S3-MinIO、多 Chroma 分片、跨实例缓存失效和通知广播尚未进行多节点 Testcontainers/E2E、并发负载、节点故障与分片恢复测试。
4. **OpenTelemetry 尚未接入。** 当前有 Micrometer/Prometheus、trace ID 和 SQLite Agent 轨迹，但没有 OTLP trace exporter、跨 Java/Python span 传播或采样配置。旧文档对此表述过度，现已纠正。
5. **供应链检查不完整。** CI 只有 npm audit；缺少 Python 依赖审计、Java CVE 扫描、容器镜像扫描、SBOM 和密钥扫描。

### P2：工程优化

1. 前端仅有 3 个 Vitest 用例，关键状态管理、错误恢复、SSE 重连、表单边界和无障碍行为主要依赖 mock E2E。
2. PyMuPDF 仍使用将废弃的 `fitz` 导入；Windows 终端中的 Python 中文结构化日志存在编码显示异常。
3. 博客和部分历史说明中的测试数量已过期，应避免复制固定计数，改为链接 CI 或生成测试报告。
4. 真实 LLM Faithfulness、Answer Relevance 和测验质量抽检需要预算、脱敏样本和周期任务，目前只有可手动执行的脚本。

## 5. 后续实施顺序

### 近期

- 为离线 RAG 定义有效指标口径和 CI 阈值，首先修正最终引用精确率的计算。

### 中期

- 使用目标领域真实脱敏样本扩展解析、检索、测验和多模态评测集，保存失败样例并做版本对比。
- 为 MinIO 和多个 Chroma 节点增加集成测试、并发压测、故障转移与容量基线。
- 接入 OpenTelemetry OTLP，贯通浏览器请求、Java Gateway、Python Agent、模型和检索阶段。
- 增加 Python、Java、镜像、SBOM 与 secret scanning，并明确安全公告处理时限。

### 长期

- 建立明确的 SLO、告警、容量模型、RPO/RTO 和定期灾难恢复演练。
- 将本地 SQLite 辅助状态迁移到可共享或可复制的存储，消除多 Python 实例下版本与轨迹数据分散的问题。
- 为插件工具增加权限范围、资源配额、隔离执行和管理员审批，避免工具能力扩展后突破租户边界。
- 基于真实学习效果数据校准复习算法、测验评分和薄弱点推断，不用 proxy 指标替代用户成效。

## 6. 发布门槛

下一次非 Beta 发布至少需要满足；前三项 P0 已完成，后三项仍未完成：

- [x] PR CI 全部通过，真实栈验收报告可追踪；合并后仍需确认 `main` CI。
- [x] 账号和文档删除在外部依赖故障后能够重试并最终证明无残留。
- [x] 备份可恢复 MySQL、原文件、对象存储、向量索引和辅助状态，并记录 RPO/RTO。
- [ ] RAG 与多模态指标使用目标领域样本，指标定义与阈值一致，真实模型抽检通过。
- [ ] 多节点部署完成容量、故障转移和数据一致性验证。
- [ ] 各语言依赖和容器镜像无未解释的 high/critical，SBOM 可生成。

在这些条件完成前，GitHub 简介和发布说明应继续使用“Beta”“本地自托管”，不使用“生产级”“完全准确”或“支持任意复杂文档”。
