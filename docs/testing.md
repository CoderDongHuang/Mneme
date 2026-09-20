# 测试说明

## Python

```powershell
cd python-agent
ruff check .
$env:MNEME_OFFLINE_EMBEDDINGS='true'
python -m pytest tests -q
```

测试环境使用确定性本地向量，不发送 Embedding API 请求。

## Java

```powershell
cd java-gateway
mvn test
```

Maven 构建会同时验证 Flyway 迁移资源、Spring 类型和 Java 17 编译。

## 前端

```powershell
cd frontend
npm ci
npm run lint
npm test
npm run build
```

浏览器验收至少覆盖 1440x900 与 390x844：认证、会话切换、资料上传状态、SSE 回答、引用抽屉、记忆确认和导航抽屉。

`npm run test:e2e` 使用 mock API 验证前端交互和响应式布局，不消耗模型额度。

## 真实全链路 E2E

`frontend/e2e/real-stack.spec.js` 覆盖真实注册、创建资料库、上传、任务轮询、Embedding、RAG、流式回答、引用、多轮对话和刷新恢复。常规 CI 使用显式启用的确定性验收模型，MySQL、Redis、Chroma、MinIO、Java、Python、Caddy 和浏览器仍为真实组件，不访问付费模型：

```bash
export MNEME_OFFLINE_EMBEDDINGS=true
export MNEME_DETERMINISTIC_TEST_LLM=true
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml -f docker-compose.ci.yml up -d --build
cd frontend
MNEME_REAL_E2E=true MNEME_E2E_BASE_URL=http://127.0.0.1:3000 npm run test:e2e:real
```

`MNEME_DETERMINISTIC_TEST_LLM` 只能用于验收环境，不能用于生产。验证外部模型质量和供应商连通性时不要设置该变量，并显式设置：

```powershell
$env:MNEME_REAL_E2E='true'
$env:MNEME_E2E_BASE_URL='http://127.0.0.1:3000'
npm run test:e2e:real
```

外部模型模式会把 `test-fixtures/rag-fixture.txt` 的虚构内容发送给配置的 Embedding 和 LLM 供应商，并产生调用费用。

## 跨存储删除与恢复演练

完整 CI 栈启动后，可运行 MySQL、Redis、Chroma、MinIO 和 SQLite 辅助状态联合清理及故障注入：

```bash
python scripts/full_stack_verification.py deletion \
  --compose-file docker-compose.yml \
  --compose-file docker-compose.selfhost.yml \
  --compose-file docker-compose.ci.yml
```

该演练覆盖 Chroma、MinIO、Redis 中断和 Java 重启，要求删除 Saga 最终完成且各存储无用户残留。备份恢复演练会创建真实数据、备份、删除、恢复并重新登录执行 RAG：

```bash
python scripts/full_stack_verification.py backup-restore \
  --compose-file docker-compose.yml \
  --compose-file docker-compose.selfhost.yml \
  --compose-file docker-compose.ci.yml
```

## RAG 评测

```bash
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml exec \
  -e MNEME_OFFLINE_EMBEDDINGS=true python-agent \
  python scripts/evaluate_rag.py
```

基线指标包括 Recall@5、MRR、最终引用 Precision/Recall、拒答和延迟。报告由 CI 作为 artifact 保存，文档不复制容易过期的测试计数。

真实模型 Faithfulness 与 Answer Relevance 评测必须使用脱敏数据、显式样本数、价格假设和单次预算上限：

```bash
python scripts/evaluate_rag.py \
  --dataset evaluation/external_rag_cases.json \
  --llm-sample-size 5 --require-sanitized \
  --input-cost-per-million 0.30 --output-cost-per-million 0.60 \
  --max-estimated-cost 0.03 \
  --real-llm-thresholds evaluation/real_rag_thresholds.json \
  --report ../artifacts/real-rag-quality-report.json
```

复杂版式回归夹具可通过 `python scripts/generate_layout_fixtures.py` 重新生成，固定样例覆盖扫描页、多栏、跨页表格、公式和带图表的电子表格；标注在 `evaluation/layout_annotations.json`。

测验质量可直接针对工作区 JSON 导出运行；默认检查结构、证据和来源覆盖，显式设置样本数时再调用真实模型评估 grounding、clarity 与 answerability：

```bash
python scripts/evaluate_quiz_quality.py evaluation/external_quiz_workspace.json \
  --llm-sample-size 4 --require-sanitized \
  --input-cost-per-million 0.30 --output-cost-per-million 0.60 \
  --max-estimated-cost 0.02 \
  --thresholds evaluation/real_quiz_thresholds.json \
  --report ../artifacts/real-quiz-quality-report.json
```

`.github/workflows/model-quality.yml` 每周运行真实 OCR、多模态、RAG 和测验抽检，也支持手动触发。预算守卫会在每次模型调用前预留最坏情况下的输出成本；脱敏扫描发现邮箱、手机号、身份证号或 API Key 形态时会在发送前失败。真实模型报告保留 30 天，并包含失败样例和评审理由。

目标领域评测集由 `evaluation/target_domain_manifest.json` 统一声明版本、数据分类、来源和样本下限。周期任务额外抽检真实 Embedding 的语义对间隔，并设置 `MNEME_REQUIRE_REAL_EMBEDDINGS=true`，API 失败时不会降级成本地向量。RAG 报告通过 `compare_quality_reports.py` 与提交基线比较，退化超过允许幅度会保留失败样例并阻断任务。

## 容量与组合故障测试

`.github/workflows/capacity.yml` 每周运行，也支持通过手动参数扩大请求数、持续时间和故障轮数。默认在双节点拓扑中写入小/中/大三档共 61 份文档，对真实检索执行 600 请求、24 并发和 120 秒负载窗口，然后连续执行 3 轮 Chroma 与 Redis 联合中断、恢复及逐库检索复查。结果和完整服务日志保留 30 天。

当前测试结果以 [GitHub Actions](https://github.com/CoderDongHuang/Mneme/actions) 和对应运行的 artifact 为准，不在说明文档中维护固定通过数量。

## 全链路冒烟

1. 注册并登录。
2. 新建资料库并上传文档。
3. 等待状态变为“可检索”且 chunk 数大于 0。
4. 创建会话并提出文档内问题。
5. 检查回答引用与原文一致。
6. 继续多轮对话，确认会话消息可重新加载。
7. 触发一条中置信度记忆并确认。
8. 在学习画像页验证记忆已出现。

## P0 生命周期验收

1. 上传文档并等待 `ready`，确认 chunk 数大于 0。
2. 点击文档“重新解析”，确认状态回到 `parsing`，完成后仍为同一文档且片段被替换而不是重复累加。
3. 删除文档，确认状态短暂为 `deleting`，任务完成后文档消失、原文件删除、检索不再返回该文档。
4. 创建账号、资料库、会话和长期记忆后删除账号；确认 MySQL 业务数据、Chroma 集合、Redis 会话和本地用户文件均被清理。任一外部清理失败时，接口应失败且用户行不会被删除。
