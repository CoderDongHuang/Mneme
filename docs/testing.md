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

基线指标包括 Hit@5、MRR 和引用元数据完整率。

真实模型 Faithfulness 与 Answer Relevance 评测需要显式指定样本数，并会消耗模型额度：

```bash
python scripts/evaluate_rag.py --llm-sample-size 20 --input-cost-per-million 0.14 --output-cost-per-million 0.28
```

复杂版式回归夹具可通过 `python scripts/generate_layout_fixtures.py` 重新生成，固定样例覆盖扫描页、多栏、跨页表格、公式和带图表的电子表格；标注在 `evaluation/layout_annotations.json`。

测验质量可直接针对工作区 JSON 导出运行；默认检查结构、证据和来源覆盖，显式设置样本数时再调用真实模型评估 grounding、clarity 与 answerability：

```bash
python scripts/evaluate_quiz_quality.py mneme-export.json --llm-sample-size 20
```

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
