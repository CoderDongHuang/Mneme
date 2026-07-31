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

## 全链路冒烟

1. 注册并登录。
2. 新建资料库并上传文档。
3. 等待状态变为“可检索”且 chunk 数大于 0。
4. 创建会话并提出文档内问题。
5. 检查回答引用与原文一致。
6. 继续多轮对话，确认会话消息可重新加载。
7. 触发一条中置信度记忆并确认。
8. 在学习画像页验证记忆已出现。
