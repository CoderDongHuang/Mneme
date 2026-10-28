# 2026-10-29 向量替换与遗漏项回归

范围为原始 Word 前言、共通要求和 Mneme 第一章，承接 [2026-10-28](ACCEPTANCE_2026-10-28.md)。原 Word、用户笔记和用户新增图片未修改。

## 本地实测

| 项目 | 结果与条件 |
|---|---|
| 旧库迁移 | 停止 Java/Python 写入后，经旧 Chroma v2 API 导出 92 集合、400 点；迁入 Qdrant 并逐条核对 ID、正文、元数据、向量、集合属性与计数。源库、快照及校验文件保留且不提交 Git；旧 Chroma 容器在新页面回归通过后停止 |
| Python 正式镜像 | Dockerfile 按 Linux Python 3.11 哈希锁全新构建通过，`pip check` 无冲突；运行时不再安装 Chroma。PyPI 超时使用清华镜像，包哈希校验未放宽 |
| Python 回归 | 初轮 Windows Python 3.10.11：644 passed、1 skipped（本机无 Tesseract）；新增锁生成器回归后，正式镜像的隔离 Python 3.11 容器：647 passed、0 skipped，含真实 OCR。Ruff 通过；原生 Windows Python 3.11 的哈希锁安装、测试与审计已在 CI 通过 |
| 真实项目页面 | `http://localhost:3000`，替换 API 专用非 root 数据库镜像后，桌面/手机 8 passed，4 workers，2.2 分钟，`--retries=0`。包含真实注册/登录、多格式入库、检索引用、流式回答、联合过滤、历史版本、越权、学习与删除、扫描 OCR、损坏文件、运行中取消/重试、供应商诊断 |
| 网络与配置 | 主栈、CI、生产和分片四种拓扑私有网络检查通过；主/分片 Compose 解析通过；旧库未迁移启动保护、迁移失败清理、空目标限制和 checksum 篡改回归通过 |
| 前批网关 | PR #36 的全部 9 项 CI 已通过并合并，含 Java 86 项、真实 MySQL/Flyway、正式 Docker 构建、供应链和分布式追踪；本批未改 Java 或前端业务代码 |

一次 Compose 容器测试误挂载真实 `/data`，触发旧数据保护且因目录结构缺少仓库脚本而失败；已改用完整源码且不挂实际数据的独立容器，最终 647 项全部通过，未删除旧库绕过保护。首次离线评测也触发旧数据保护，随后在独立临时 Qdrant/词法目录重跑四组，未触碰原生旧资料。

## 检索与供应链

四组共 140 题在 Qdrant 本地模式通过原有门禁，P95 ≤ 250ms，未修改阈值。原始报告见 [release-evidence-2026-10-29](../python-agent/evaluation/release-evidence-2026-10-29/)。这是离线检索验证，不重新计算或覆盖此前真实模型的小样本成绩；HTTP 云模型语义与复杂 OCR 不保证普遍准确。

Linux Python 3.11 锁文件 116 包；Windows wheel 按目标平台元数据递归补齐依赖闭包后为 119 包，均计算 SHA-256。首次 Windows CI 发现原生成器只复制 Linux 清单而遗漏平台依赖，已修复生成器并增加平台 marker、传递依赖和冲突回归；补入 colorama、tzdata 和兼容 Python 3.11 早期补丁版本的 async-timeout。删除三个 Chroma pip-audit 忽略；CI 增加 Qdrant 镜像扫描及官方镜像 provenance 产物。新扫描不扩大 `ignore-unfixed` 原策略，扫描通过不等于零漏洞。

本机 Docker Hub 拉取超时，先使用 DaoCloud 镜像缓存；随后从 [CI 40733338222](https://github.com/CoderDongHuang/Mneme/actions/runs/40733338222) 下载官方 Docker Hub 拉取的 provenance，确认官方摘要与本机缓存一致：`sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2`。派生镜像 Dockerfile 固定此官方摘要，CI 同时保存基础与派生镜像信息。

首次供应链扫描发现官方镜像附带 Dashboard 的 follow-redirects/undici 共 5 项 HIGH。Mneme 只用数据库 API，因此派生镜像实际删除整个未用 Dashboard 并禁用静态服务，保留官方数据库二进制、运行库及完整 Rust SBOM；没有新增漏洞忽略，也没有单独删除 SBOM 隐藏依赖。首次全栈启动因非 root 用户无法写默认快照目录失败，已将快照与初始化标记移入数据卷，并以 UID 1001 验证健康响应 200。真实旧库又发现 root 所属 WAL 不可写，主栈加入无网络的一次性目录归属初始化，数据库仍以非 root 用户运行；CI 使用 runner UID 保持备份可读写。

[CI 40738984759](https://github.com/CoderDongHuang/Mneme/actions/runs/40738984759) 的供应链门禁通过；下载扫描 JSON 核对派生镜像的 81 个系统包与 748 个 cargo 包仍在扫描范围内，既定 HIGH/CRITICAL、`ignore-unfixed` 策略下未命中漏洞。基础官方摘要再次一致。这个结果不代表未修复低等级漏洞、未知漏洞或法律审查全部消失。

## 文档与发布范围

[CI 40738984759](https://github.com/CoderDongHuang/Mneme/actions/runs/40738984759) 对代码提交 `7403e7d67951a865a6ccaca4118abb4e350010ff` 的全部 9 项检查通过：Linux Python、Windows Python 3.11 哈希锁安装与审计、Java/MySQL、React、真实 OCR/Qwen-VL 质量、离线空库演示、供应链、双节点与追踪、全栈 P0。全栈已执行真实页面、Redis 租约续期/崩溃接管、解析取消筛选、输入拒绝指标、运行趋势、费用策略、Qdrant/对象存储/Redis/Java 故障删除及备份恢复后的登录与问答。最终文档提交仍需其自身检查通过后才合并。

README、原生 Windows 启停、开发、自部署、生产、Embedding、RAG、测试、备份恢复、故障注入、容量工作流和安全说明均改用新库。新增[迁移指南](VECTOR_STORE_MIGRATION.md)说明停写、空目标、私有快照、逐点验证、分片/Demo、历史备份和回滚；旧 Chroma 历史报告不改造成 Qdrant 成绩。

原路线图中的基准评测、可关闭混合召回、声明证据、来源权限/版本、解析预览、取消重试、删除与备份、学习复习和供应商诊断仍按[对照表](ROADMAP_COVERAGE.md)回归。保留的工程边界包括：owner 租约不是 fencing、跨 MySQL/向量/词法/文件非整体事务；应用分片不等于原生高可用；生产 KMS/异地恢复需实际部署资源；第三方许可证法律兼容性不能由 SBOM 单独认定。不会把这些边界写成已经被数据库替换消除。
