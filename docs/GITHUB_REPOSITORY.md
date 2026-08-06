# GitHub 仓库发布信息

## About 简介

推荐中文：

> 支持结构化 RAG、三级记忆、可追溯引用与 SSE 流式回答的开源个人学习助手，基于 React、Spring Boot、FastAPI 和 LangGraph。

推荐英文（更适合 GitHub About，字符更短）：

> Self-hosted learning assistant with structured RAG, three-tier memory, cited answers and streaming responses.

Website 暂时留空；如果以后发布在线演示，再填写演示地址，不要填写本地地址。

## Topics

```text
ai-agent
rag
langgraph
fastapi
spring-boot
react
chroma
llm
knowledge-base
personalized-learning
self-hosted
docker-compose
```

## 技术栈

- Frontend：React 19、Vite 8、React Router、React Markdown、Lucide
- Gateway：Java 17、Spring Boot 3.2、MyBatis-Plus、Flyway、JWT、SSE
- Agent：Python 3.11、FastAPI、LangGraph、LangChain、Pydantic
- AI：DeepSeek、Qwen、DashScope Embedding、Chroma
- Data：MySQL 8、Redis 7
- DevOps：Docker Compose、Caddy、GitHub Actions
- Test：Pytest、Ruff、Maven Test、ESLint、Vitest、Playwright

## 推荐仓库名称与副标题

- Repository：`Mneme`
- 中文名：`忆知`
- 副标题：`一个会使用资料、记住学习状态并给出可追溯回答的个人学习 Agent`

## 首个 Release

版本：`v0.2.0`

标题：

```text
Mneme v0.2.0：支持中文 OCR 与本地完整自部署的学习助手
```

说明：

```markdown
Mneme v0.2.0 完成了个人学习助手的本地自部署闭环：

- React 学习工作台与登录注册
- PDF/DOCX/PPTX/XLSX/CSV/Markdown/TXT/HTML 资料解析
- LangGraph Agent 决策链与结构化 RAG
- 带文档、页码、章节和原文片段的引用回答
- 工作记忆、短期记忆和长期记忆
- 记忆蒸馏、置信度分级与用户确认
- DeepSeek 主模型、Qwen 备用模型和熔断降级
- Java Gateway 的认证、会话、资料任务与 SSE 转发
- Docker Compose 自部署
- 中英文 Tesseract OCR、PDF 版面还原与可选 Qwen-VL 图片理解
- Mailpit 本地密码重置邮件
- RAG 指标评测与真实跨服务 E2E 入口

多模态解析会消耗 DashScope 额度，默认关闭；升级前请备份 `data/` 目录。
```

## 发布前检查

- GitHub Actions 主分支全部通过。
- 仓库未包含 `.env`、API Key、用户上传文件、测试结果和本地数据。
- README 中的 Docker 命令在干净环境验证通过。
- `LICENSE`、已知限制和数据备份说明可见。
- 创建 `v0.2.0` 标签并附上 Release Notes。
- 至少添加 3 张真实截图：登录页、资料库上传状态、带引用的对话页。
