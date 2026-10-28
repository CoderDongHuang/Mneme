# 2026-10-29 向量替换与遗漏项回归

范围为原始 Word 前言、共通要求和 Mneme 第一章，承接 [2026-10-28](ACCEPTANCE_2026-10-28.md)。原 Word、用户笔记和用户新增图片未修改。

## 本地实测

| 项目 | 结果与条件 |
|---|---|
| 旧库迁移 | 停止 Java/Python 写入后，经旧 Chroma v2 API 导出 92 集合、400 点；迁入 Qdrant 并逐条核对 ID、正文、元数据、向量、集合属性与计数。源库、快照及校验文件保留且不提交 Git；旧 Chroma 容器在新页面回归通过后停止 |
| Python 正式镜像 | Dockerfile 按 Linux Python 3.11 哈希锁全新构建通过，`pip check` 无冲突；运行时不再安装 Chroma。PyPI 超时使用清华镜像，包哈希校验未放宽 |
| Python 回归 | Windows Python 3.10.11：644 passed、1 skipped（本机无 Tesseract）；正式镜像的隔离 Python 3.11 容器：645 passed、0 skipped，含真实 OCR。Ruff 通过 |
| 真实项目页面 | `http://localhost:3000`，桌面/手机 8 passed，4 workers，2.3 分钟，`--retries=0`。包含真实注册/登录、多格式入库、检索引用、流式回答、联合过滤、历史版本、越权、学习与删除、扫描 OCR、损坏文件、运行中取消/重试、供应商诊断 |
| 网络与配置 | 主栈、CI、生产和分片四种拓扑私有网络检查通过；主/分片 Compose 解析通过；旧库未迁移启动保护、迁移失败清理、空目标限制和 checksum 篡改回归通过 |
| 前批网关 | PR #36 的全部 9 项 CI 已通过并合并，含 Java 86 项、真实 MySQL/Flyway、正式 Docker 构建、供应链和分布式追踪；本批未改 Java 或前端业务代码 |

一次 Compose 容器测试误挂载真实 `/data`，触发旧数据保护且因目录结构缺少仓库脚本而失败；已改用完整源码且不挂实际数据的独立容器，最终 645 项全部通过，未删除旧库绕过保护。首次离线评测也触发旧数据保护，随后在独立临时 Qdrant/词法目录重跑四组，未触碰原生旧资料。

## 检索与供应链

四组共 140 题在 Qdrant 本地模式通过原有门禁，P95 ≤ 250ms，未修改阈值。原始报告见 [release-evidence-2026-10-29](../python-agent/evaluation/release-evidence-2026-10-29/)。这是离线检索验证，不重新计算或覆盖此前真实模型的小样本成绩；HTTP 云模型语义与复杂 OCR 不保证普遍准确。

Linux 与 Windows 锁文件分别按 Python 3.11 解析、下载和计算哈希，各 116 包。删除三个 Chroma pip-audit 忽略；CI 增加 Qdrant 镜像扫描及官方镜像 provenance 产物。新扫描不扩大 `ignore-unfixed` 原策略，扫描通过不等于零漏洞。

本机 Docker Hub 拉取超时，临时使用 DaoCloud 镜像缓存启动 Qdrant，缓存摘要 `sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2`。Docker 官方 API 和 GitHub 大文件下载不可达，不能据此宣称已完成本地镜像来源核验；正式配置固定官方仓库，CI 直接拉取官方镜像并输出摘要供核对。

## 文档与发布范围

README、原生 Windows 启停、开发、自部署、生产、Embedding、RAG、测试、备份恢复、故障注入、容量工作流和安全说明均改用新库。新增[迁移指南](VECTOR_STORE_MIGRATION.md)说明停写、空目标、私有快照、逐点验证、分片/Demo、历史备份和回滚；旧 Chroma 历史报告不改造成 Qdrant 成绩。

原路线图中的基准评测、可关闭混合召回、声明证据、来源权限/版本、解析预览、取消重试、删除与备份、学习复习和供应商诊断仍按[对照表](ROADMAP_COVERAGE.md)回归。保留的工程边界包括：owner 租约不是 fencing、跨 MySQL/向量/词法/文件非整体事务；应用分片不等于原生高可用；生产 KMS/异地恢复需实际部署资源；第三方许可证法律兼容性不能由 SBOM 单独认定。不会把这些边界写成已经被数据库替换消除。
