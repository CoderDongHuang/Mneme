# 2026-10-27 路线图落实记录

范围：用户提供的《GitHub 项目全面优化与功能演进路线图》的前置通用工程要求及 Mneme 第一章。其产品建议作为实施底稿，并不构成已证明存在的缺陷。其他项目章节不在本仓库实施。

## 通用工程

| 要求 | 实现与验收入口 | 范围与后续 |
| --- | --- | --- |
| 陌生用户最短启动路径 | [README](../README.md)、[隔离演示](DEMO.md)、`.env.example`、`scripts/demo.py`；CI Offline demo clean install 从空数据库执行真实浏览器上传、引用回答 | 首次构建需要网络与 Docker；演示返回明确标识的原文摘录，测验生成需真实模型 |
| 可复现依赖、安全检查、构建 | 哈希 Python 锁、npm lock、Maven；CI Linux/Windows、前端浏览器、供应链、SBOM | 锁定依赖不代表没有漏洞；当前五项有期安全例外见 [说明](security-exceptions.md) |
| 业务闭环与集成 | Full-stack P0 acceptance、Distributed scaling and tracing、真实 OCR 工作流 | 本机 Docker 不可用时依赖隔离 CI 的完整验收，不将 mock 单元测试称为真实集成 |
| 可观测性与错误 | request/trace 传播、任务持久化/有限重试、服务健康与业务探测分离；设置页模型检测 | 日志规则脱敏覆盖凭证、邮箱等已定义模式，不能保证识别任意个人信息 |
| 发布与社区 | README、独立 bug/feature Issue 模板、[发布说明](RELEASE_NOTES_2026-10-27.md)、贡献指南 | 仓库 MIT 不替代第三方许可证；SBOM/漏洞门禁不能代替完整人工许可证兼容审查 |

## Mneme 第一章

| 优先项 | 本轮实现及现有能力 | 验证与真实边界 |
| --- | --- | --- |
| P0 RAG 基准 | 110 题多格式离线检索集，12 题版本化目标集；另加合成注入/冲突专用集；schema 3 区分检索代理指标与真实生成/核验/裁判 | `evaluate_rag.py`、`test_rag_quality_gate.py`；真实模型 8 题含 2 道无答案题。小样本与模型裁判不能代表真实用户准确率。专用集的 `expected_answer_points` 供人工复核，不是自动计分项 |
| P0 混合召回 | Dense + FTS5 BM25 + RRF，每通道名次；独立查询改写开关、可选 rerank；引用抽屉展示排序信号、页码、索引时间、hash/parser 版本 | `test_retriever.py` 等；词法候选从当前用户 Chroma 重读以排除已删除/陈旧资料。支持知识库选择，**日期/标签/文档联合过滤尚未交付**；排序信号不是概率 |
| P0 声明与引用 | 生产 QA prompt 限制无证据展开；同步/SSE 展示前逐单元模型核验，并强制对应引用的逐字原文引句；缺漏、超时、越界、无证据均拒答；保留有用/不相关/不支持反馈 | `test_grounding.py`、`test_evidence_chat.py`、Java 来源协议测试。模型核验仍可能误判；QA 流式回答需等待核验。非 QA 闲聊/学习建议不承诺逐句资料核验 |
| P0 来源权限与版本 | 当前租户查询、Java 打开原文权限检查；来源带文件 hash、parser 版本与定位信息；删除后正文不可继续返回，审计痕迹保留 | 不保证所有复杂 PDF 坐标精确；旧会话打开当前文档时应对照 hash，尚无所有历史版本正文的自动精确跳转保证 |
| P0 导入可诊断 | 持久 ProcessingTask、有界重试、工作区取消/手动重试；文档 ready/partial/failed；逐页警告、parser/hash/index 时间，Java V19 保存 parseReport，前端报告面板 | `test_document_parser.py`、ingestion/processing 测试。内部状态名为 pending/processing/retry/completed 等；只支持取消等待中的解析任务，不能中断已经执行的解析。复杂表格/公式仍需人工核对；**逐区域 OCR 置信度热图、完整逐页表格与 chunk 预览未交付** |
| P0 删除一致性 | 删除 saga、派生索引/缓存/记忆清理、失败恢复与跨用户测试；词法过期结果禁止绕过当前向量权限 | 跨存储操作不是整体事务；强杀/存储不可用需要重试及审计，不能承诺零恢复窗口 |
| P0 备份恢复 | 验签/解密/路径校验、空间预检、schema 上限；操作前持久恢复包，导入失败恢复旧 SQL/目录，回滚失败保持应用停止；报告写失败不跳过回滚；同 checkout 排他锁 | `test_backup_restore.py` 注入导入/回滚/报告写盘失败；全栈恢复演练。锁不协调另一 checkout；schema 上限来自本代码 Flyway 迁移，非读取归档 SQL 的实际迁移历史；强杀/掉电需人工恢复。外部直连 MySQL 写入须由运维暂停 |
| P0 Embedding 迁移 | 模型 profile/维度/有限数值保护，不把云失败替代向量混入集合；非空旧集合无 profile 时拒绝检索/写入；显式重建脚本默认 dry-run、快照与异常回滚 | `rebuild_embeddings.py`、embedding/profile 测试。需要停服与备份；不保证断电原子性。`--apply` 不得被当成无风险自动升级 |
| P1 学习闭环 | 已有来源卡片、题目编辑/拒绝/删除/导出、SM-2 复习与薄弱点、计划控制；WorkspaceService 验证用户与消息归属 | Workspace/quiz 测试及真实 quiz 工作流。模型生成题目仍需用户审查，不用机械输出的来源号代替语义质量 |
| P1 配置诊断 | Chat/Embedding/Rerank/OCR profile、合成请求探测、超时/缓存、缺密钥/配额/不支持分类；前端不回显完整密钥 | provider diagnostics 测试及 Settings 界面。当前为部署方服务端配置；切换 embedding 需显式迁移，不自动重写已有资料 |

## 发布判定

当前目标是可运行、可诊断、边界明确的个人自部署 Beta。未实现项已在上表保留，不能宣称整份路线图全部完成。新生成/核验协议与旧评测不可直接比较；趋势工作流需要同 provenance 的独立历史运行，首次采集状态为 insufficient_history。现场 KMS/S3、多区域可靠性、任意资料质量及完整许可证审查需要后续专项验收。
