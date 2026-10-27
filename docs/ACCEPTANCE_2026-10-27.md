# 2026-10-27 最终回归记录

范围是路线图前言/共通要求及 Mneme 章，回归之前 PR #30–#33 的功能和本轮补全。工作分支 `codex/roadmap-completion-20261027`，基于 `0259a0b`；最终合并提交与 CI 可在 GitHub PR 查看。用户的 Word、调试笔记和新增图片不修改或提交。

## 实际运行环境

- 主项目：<http://localhost:3000/auth>；真实 Java/Python/MySQL/Redis/Chroma/Caddy/Mailpit，本机配置的真实 Qwen 模型及 DashScope 云 embedding（查询改写开启，rerank 关闭）。浏览器从同源代理调用，地址只在运行 Docker 的本机可用。
- 独立验收：frontend 13000、Java 18080、Python 18001、MySQL 13306、Redis 16379、Mailpit 18025，项目名 `mneme-acceptance-20261027`，独立目录和空数据。真实 RustFS S3 兼容服务，确定性验收 LLM/离线 embedding。
- 空库环境按 base+selfhost+ci+独立端口覆盖启动；应用镜像复用本轮构建结果，不声称从零下载依赖。删除与恢复故障操作仅对独立环境运行，未清空主项目数据。

## 测试与命令

| 检查 | 结果/范围 |
|---|---|
| `.venv/Scripts/python.exe -m pytest python-agent/tests -q` | 623 通过、1 跳过；本机缺 Tesseract 的测试在容器真实 OCR 流程另测 |
| Ruff：app/tests/scripts 和根 scripts | 通过 |
| Maven `-f java-gateway/pom.xml test`，Docker 可用 | 85 项、0 失败、0 跳过；真实 MySQL V1 升级、V13 升级和 V20 幂等校验 |
| 前端 lint / Vitest / build / bundle budget | 26 项通过；13 懒加载路由，首屏 JS gzip 78.88 KiB；Docker 构建 npm 审计 0 漏洞 |
| 真实 `real-stack.spec.js` | 主项目桌面/手机各 1 项通过；独立空库/恢复后的 URL 另 1 项通过：注册、错误密码、登录、入库、两轮 RAG、引用与刷新 |
| `roadmap-stack.spec.js` 的资料闭环 | 主项目桌面和移动分别通过；TXT/PDF/CSV/XLSX/MD/HTML/DOCX/PPTX、标签/日期/文档过滤、非法日期、跨用户、hash 历史版本/恢复、测验证据/评分、复习导出、删除与全部受保护路由 |
| 真实解析异常 | 扫描页文字和区域置信度、多栏表格、损坏 PDF 的错误、processing 取消后 cancelled、新任务 ID 重试、唯一 chunk、浏览器实际加载 OCR 原图，通过 |
| 真实界面交互 | 桌面和移动均通过；保存标签、联合过滤、空结果、切库清空筛选和旧结果、设置页四类供应商检测、无横向溢出 |
| 删除故障注入 | 独立栈通过 Chroma、RustFS、Redis 中断与 Java 重启，核对各存储删除完成 |
| 加密备份/恢复 | 独立栈通过备份—删除—恢复—重新登录—引用问答；报告 status=completed，最终复测 RPO 59.919 秒、RTO 28.890 秒，仅为本次样本 |
| schema 核对 | 实际 MySQL 的 18 条 Flyway 历史名称/版本/CRC32 与迁移文件匹配，最高 V20 |

最终真实地址 8 项全部通过（`artifacts/pr34-final-real-url.log`），前端最后一次修复后 lint、26 项单测和容器生产构建/预算通过。

本地原始日志保存在忽略的 `artifacts/`，可公开的模型报告在 [release-evidence-2026-10-27](../python-agent/evaluation/release-evidence-2026-10-27/)。不得上传数据库、备份包、实际用户数据或环境密钥。

真实界面可重复命令（在 frontend 下，先启动主项目；需要已配置供应商，可能产生少量费用）：

```powershell
$env:MNEME_REAL_E2E='true'
$env:MNEME_E2E_BASE_URL='http://127.0.0.1:3000'
npx playwright test e2e/real-stack.spec.js --project=桌面端 --retries=0
npx playwright test e2e/roadmap-stack.spec.js --retries=0
```

常规 CI 仅运行无需付费模型的解析异常与界面交互两项；完整测验闭环须真实模型配置。停止或删除数据前参见 [测试指南](testing.md)；不能把破坏性脚本指向主项目。

## 质量与失败记录

- 本轮两次独立目标集真实模型评估各 8 题（6 可答、2 无答案），faithfulness/relevance=1.0，正确拒答=1.0，可答拒答=0；同数据、prompt、模型配置比较通过。要点评分严格校验索引、布尔结论与非空理由。
- 额外 4 题注入/冲突/缺证据抽样的要点覆盖、faithfulness、relevance、正确拒答均为 1.0；原始首条召回精度 0.75 未达 0.8，**整体补充门禁失败**。原报告不改写，门限不降低；无答案仍可能召回主题相近候选。
- 历史 `no_answer_evidence_absence` 在空来源标注时恒真，不是拒答测试；真正拒答使用生成后指标和答案复核。
- 初次并发性能检查 P95=347.49ms 超过 250ms，保留失败日志；独立复测 186.47ms，最终关闭改写/重排的 110 题离线基线 P95=15.14ms，Recall@K=1.0、MRR=0.9532，原 250ms 门禁通过。离线 embedding 的延迟不代表云接口延迟。
- 可选 DashScope 重排在 4 题抽样、阈值 0.25 下原始首条精度达 1.0，但 P95=4240.11ms；扩大至 110 题时召回降至 0.5238、P95=32551.02ms。拒绝将该配置设为默认，保留两个失败实验报告。默认 rerank 关闭、最小分数为 0；云 embedding 实验与离线基线不可直接比较。
- 真实回归发现并修复资料库加载完成前发送导致空范围，以及项目名“计划”误路由为建议、手机长用户名撑宽。
- 旧浏览器定位器在带图标容器中寻找后代文字失败，改为对可见范围容器本身断言全文，不修改功能行为。
- PR #34 首轮 Linux CI 检出短文字层页面启用 OCR 后跳过页眉清理；已按原文字块坐标修复，并新增不依赖 Tesseract 的 OCR 成功路径回归。Linux 容器真实 Tesseract 断言和本机 623 项通过；扫描正文保护继续保留。

- PR #34 后续 CI 发现两处旧验收前提失效：扩容脚本绕过目录使用虚构资料 ID，空库删除演练期待凭空回答资料识别码。现改为正式建库/上传并等待 ready，以及验证完整 SSE 无证据拒答；保留租户与来源权限校验。扩容拓扑补齐网关与两套 Agent 的共享文件卷。新增 6 项空库流验收回归。

## 2026-10-28 发布前复核

- `6e0c751` 的 [9 项 CI](https://github.com/CoderDongHuang/Mneme/actions/runs/40541953447) 全部通过，包括正式资料目录下的双分片检索、故障恢复、跨实例通知和完整追踪，以及删除与备份恢复。
- 发现并修复默认 `com.mneme=DEBUG` 会让 MyBatis 记录 SQL 绑定值的问题；默认应用和 mapper 均为 INFO。重建网关后，真实注册、空资料拒答和上传日志未出现 SQL 参数或密码哈希，Java 85 项/0 跳过通过。
- 最终网关镜像的主项目桌面/手机冒烟 2/2 通过，日志 `artifacts/pr34-release-smoke.log`；真实接口空库拒答及正式建库上传/ready 通过，日志 `artifacts/pr34-final-service-check.log`。
- 独立验收栈曾被旧源码挂载覆盖镜像；同步本轮源码后重新通过 Chroma/S3 兼容存储/Redis/Java 重启四类删除故障，以及加密备份—删除—恢复—登录—引用问答。日志 `artifacts/pr34-deletion-verifier-fix.log` 与 `artifacts/pr34-backup-final.log`。主项目数据未参与破坏性演练。
- 最后日志修复的提交仍须 PR 最新检查全部通过后才合并；最终状态以 PR 检查和合并提交为准。

## 文档对照

逐项核对原文的 P0/P1，实现、验收和未完成边界统一写入 ROADMAP_COVERAGE；同步 README、API、自部署、rollout、RAG、测试、当前状态与发布说明。没有把旧解析报告补造、同主题无答案召回、强杀锁、上游公告、生产云和许可证审查写成“已解决”。当前仍是私有部署 Beta，不能据此宣称生产风险全消除。
