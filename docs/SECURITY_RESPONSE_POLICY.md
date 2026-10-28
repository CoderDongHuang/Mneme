# Mneme 安全公告处理策略

适用范围包括 Python、Java、前端依赖，容器基础镜像、构建工作流及仓库密钥。

## CI 门禁

- 已修复版本可用的 High 或 Critical 漏洞不得合并；临时例外必须记录 CVE/GHSA、影响判断、负责人和到期日。
- 密钥扫描命中不得合并；确认泄漏后立即撤销凭据并清理历史。
- 每次 PR 和 `main` 推送生成依赖/镜像扫描报告及 CycloneDX SBOM，作为可下载的 CI 产物保留。

## 处理时限

| 严重度 | 首次确认 | 修复或隔离 |
|---|---:|---:|
| Critical | 4 小时 | 24 小时 |
| High | 1 个工作日 | 7 天 |
| Medium | 5 个工作日 | 30 天 |
| Low | 下个计划周期 | 90 天 |

无法在时限内升级时，必须禁用受影响功能、限制暴露面或部署可验证的缓解措施，并在到期前重新审查例外。

## 当前例外与历史处理

当前无项目主动配置的漏洞扫描例外。2026-10-29 移除 Chroma 包、服务及三个 pip-audit 忽略项，改用 Qdrant 1.20.0；这是替换受影响组件，不是声称 Chroma 上游已修复。运行时和向量库镜像均纳入扫描。迁移、回滚和旧数据保护见 [迁移指南](VECTOR_STORE_MIGRATION.md)。历史处理记录如下。

2026-10-27 Java 镜像复扫：Brotli `CVE-2026-111497` 通过构建时 `apk upgrade --no-cache` 获取发行版补丁，镜像扫描继续强制拦截。

2026-10-28：Spring `CVE-2026-47884`（XSLT/wildcard view）和 `CVE-2026-47890`（SSE view fragments）通过 Spring Boot 4.0.9 / Spring Framework 7.0.10 迁移处理。删除两项 `.trivyignore` 忽略及旧版适用性检查，继续执行普通 Java 依赖和镜像扫描。MyBatis、springdoc、RestClient、Flyway 和 OpenTelemetry 使用兼容的 Boot 4 模块；JSON 暂沿官方 Jackson 2 兼容模块维持已有持久化契约。验收证据见 [本轮记录](ACCEPTANCE_2026-10-28.md)。

2026-10-01 镜像复扫发现 Jackson Databind `2.21.6` 的 `CVE-2026-91776` 和 `CVE-2026-91777`（High），已将 Jackson BOM 升级到修复版本 `2.21.7`；保持镜像 High/Critical 门禁，不增加例外。

2026-10-01 复核：PyJWT 的 `GHSA-42vr-xj54-vc7v` / `CVE-2026-101918` 已通过升级 `2.14.0` 到 `2.15.0` 修复，锁文件使用核实的官方 wheel 哈希，并覆盖未验签深层 JSON 载荷应返回 `DecodeError` 的回归。启用 LLM 日预算时拒绝非有限预算、价格和共享计数值，且预留的输出 token 上限实际传给模型。备份恢复拒绝目标目录链接及 Windows 特殊文件路径。2026-10-27 曾有五项例外；Spring 7 迁移后曾剩三项 Chroma 例外，现已随组件替换删除。

2026-10-27/28 历史复核：`PYSEC-2026-3813` / `CVE-2026-45830`、`PYSEC-2026-3814` / `CVE-2026-45833`、`PYSEC-2026-3815` / `CVE-2026-45831` 仍覆盖 Chroma 0.6.3，影响范围至 1.5.9，未确认官方修复。此前的内部网络隔离只降低暴露面，未修复漏洞；原计划 2026-11-10 到期的三项例外已于 2026-10-29 删除。Qdrant 继续使用私有网络，`scripts/check_vector_isolation.py` 检查主栈、CI、生产和分片拓扑。新版客户端不安装 fastembed 或远程模型加载组件；模型由 Mneme 独立供应商层调用。旧容器及备份仍须隔离保管。

2026-10-28 PR #35 供应链门禁发现新增公告：Guava 33.4.8-jre 的 CVE-2026-102554 与 Snappy Java 1.1.10.7 的 CVE-2026-108106、CVE-2026-93451。通过 Maven dependencyManagement 分别固定官方修复版 33.7.2-jre、1.1.10.9；未增加扫描忽略项。Java 完整回归及依赖/运行镜像扫描通过后合并。本批 Spring 迁移移除原两项例外，Chroma 替换处理见上文。
