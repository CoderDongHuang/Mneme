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

`frontend/e2e/real-stack.spec.js` 覆盖真实注册、创建资料库、上传、任务轮询、Embedding、RAG、流式回答和引用。为了避免 CI 自动消耗模型额度，必须显式设置：

```powershell
$env:MNEME_REAL_E2E='true'
$env:MNEME_E2E_BASE_URL='http://127.0.0.1:3000'
npm run test:e2e:real
```

该测试会把 `test-fixtures/rag-fixture.txt` 的虚构内容发送给 DashScope Embedding，并把测试问题发送给配置的 LLM。

## RAG 评测

```bash
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml exec \
  -e MNEME_OFFLINE_EMBEDDINGS=true python-agent \
  python scripts/evaluate_rag.py
```

基线指标包括 Hit@5、MRR 和引用元数据完整率。

## 全链路冒烟

1. 注册并登录。
2. 新建资料库并上传文档。
3. 等待状态变为“可检索”且 chunk 数大于 0。
4. 创建会话并提出文档内问题。
5. 检查回答引用与原文一致。
6. 继续多轮对话，确认会话消息可重新加载。
7. 触发一条中置信度记忆并确认。
8. 在学习画像页验证记忆已出现。
