# 2026-10-28 遗漏项复查与实际验收

范围：原路线图前言、共通工程要求与第 1 章 Mneme。承接 [上轮验收](ACCEPTANCE_2026-10-27.md)，原 Word、用户笔记和新增图片不改写。当前面向个人/小团队私有部署 Beta。

## 本轮实测

| 项目 | 结果与条件 |
|---|---|
| Python 全量与静态检查 | Windows Python 3.10.11：637 passed、1 skipped（本机无 Tesseract）；Ruff 通过。发布锁和容器为 Python 3.11，Linux/Windows 3.11 另由 CI 验证 |
| 全新 Python 镜像 | 锁文件哈希强制校验，jieba 0.42.1 sdist 构建/安装与 posseg 导入通过；官方 PyPI 超时后使用清华镜像，不更改包哈希 |
| Windows 锁生成器 | 对仅含 jieba 的独立输入实跑，生成的 sdist SHA-256 与两平台提交锁一致；不以该小测声称重新下载验证了整份 Windows 锁 |
| 真实 Redis | `check_ingestion_lease.py` 四项全真：超过 TTL 仍续租、重复任务拒绝、子进程强杀后恢复、继任 owner 不被旧 owner 续租或删除 |
| 实际项目 URL | `http://localhost:3000`，全新 Python 镜像启动后运行 `real-stack.spec.js --retries=0`，桌面/手机 2 passed（30.0s）。真实注册、错误密码提示、再次登录、入库、检索引用、外部模型、多轮与刷新恢复通过 |
| Java/前端既有回归 | 本轮前阶段 Java 85 passed（含真实 MySQL/Flyway）；前端 26 项、lint、构建和包预算通过。本批未改 Java/前端业务实现 |

## 检索与模型证据

提交的原始 JSON 位于 [release-evidence-2026-10-28](../python-agent/evaluation/release-evidence-2026-10-28/)。未改写历史失败报告。

| 最终离线集合 | 题数 | Recall@5 | MRR | 首条证据精度 | 无答案空召回 | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| rag_cases | 110 | 1.0 | 0.9556 | 0.9238 | 1.0 | 13.88 |
| adversarial | 4 | 1.0 | 1.0 | 1.0 | 1.0 | 9.14 |
| target_domain | 12 | 1.0 | 1.0 | 1.0 | 1.0 | 9.78 |
| retrieval_holdout | 14 | 1.0 | 1.0 | 1.0 | 1.0 | 26.81 |

共 140 题通过原离线门禁（P95 ≤ 250ms）。schema 4 无答案评分使用实际空召回 `not chunks`，修复旧 `expected_sources=[]` 恒真；新基线 v2 仅为离线检索基线。比较脚本拒绝 schema、评分、focus 开关、检索配置不同的报告；真实模型基线不能静默退化为离线比较。周期趋势增加检索源码与 embedding 实现摘要，旧模型趋势须重新 bootstrap。

中文具体名词过滤减少无关片段进入生成；有限的词性、关键词和同义表达并非普遍语义判断。新增 holdout 的 14 题来自单一短篇合成材料，未覆盖真实用户资料分布，不能宣称普遍准确率或所有无答案问题都正确拒答。

真实云 embedding 初测 P95=2257.86ms；将改写批量 embedding/查询后 P95=915.23ms，仍不满足 250ms。两份失败证据分别为 `holdout-real-rag.json`、`holdout-real-rag-batched.json`。独立云接口工程预算新设 P95 ≤ 3000ms，质量门限未变；按该 profile 独立复测 `holdout-cloud-profile.json` 为 704.57ms，通过。8 个真实模型样本含 2 个无答案题：faithfulness、relevance、拒答准确率均 1.0，可回答题拒答率 0；估算费用 0.018782 美元，不是供应商账单。不能把云 profile 通过称为原 250ms 门槛通过。

## 原文逐项复查

[路线图对照](ROADMAP_COVERAGE.md) 保留逐项实现、验收和边界。前阶段已实测的多格式/复杂版式、联合过滤、来源版本/权限、取消重试、学习复习导出、供应商诊断、空库演示、删除故障和备份恢复继续由现有 CI 回归。本轮新增真实 Redis 强杀检查和四组离线检索 CI，避免只修本机样例。

租约为 owner 比较的 60 秒 TTL/20 秒心跳，每个检查点同步校验 owner。embedding 返回后重新检查，再写向量。续租失败停止后续流程；不是 fencing，冻结发生在检查与写入之间仍可能竞态，跨 MySQL/向量/词法/文件不是整体事务。外部调用只能等待返回或超时。

当前尚有三项 Chroma 安全公告例外；隔离不等于补丁。Spring 两项例外通过下述迁移移除。真实 AWS KMS/异地 S3、完整许可证法律兼容性和任意复杂 OCR 的正确性不能用本机合成测试替代。所有当前结论以报告和实际 CI 结果为依据。

## Spring 7 安全迁移

网关迁移至 Spring Boot 4.0.9 / Spring Framework 7.0.10，配套 MyBatis Plus 3.5.18.1、springdoc 3.2.0。Flyway、RestClient 和 OpenTelemetry 使用 Boot 4 模块，Jackson 2 兼容模块保持已有 JSON 契约，OTLP tracing 使用新配置路径；Prometheus 保留且不额外启用 OTLP metrics exporter。最终依赖下 Java 85 tests passed、0 skipped，含真实 MySQL/Flyway。删除两项 Spring CVE 忽略及到期适用性 guard，后续依赖和镜像扫描继续阻断漏洞。
