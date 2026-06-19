# Mneme — 三级记忆个人学习助手

> 不是一次性问答机器，它会记住你的偏好、薄弱点和学习进度，越用越懂你。

## 架构

```
浏览器 (原生 JS SPA)
  ├─ SSE 流式 (开发模式直连 Python)
  └─ WebSocket (生产模式经 Java Gateway)
         │
Java Gateway (Spring Boot 3)  ←→  MySQL · Redis
  ├─ JWT 鉴权
  ├─ 知识库 CRUD
  ├─ WebSocket 实时推送
  └─ HTTP ──→ Python Agent (FastAPI + LangGraph)
                   ├─ Chroma (向量检索 + 长期记忆)
                   ├─ DeepSeek-V3 (LLM 推理)
                   └─ DashScope Embedding (向量化)
```

## 核心功能

- **三级记忆**：工作记忆(滑动窗口) → 短期记忆(LLM 摘要压缩) → 长期记忆(Chroma 持久化 + 语义去重 + 衰减淘汰)
- **Agent 决策链**：LangGraph 状态图编排，意图分类(qa/review/suggest/general) → 条件分支检索 → 推理 → 记忆回写
- **流式输出**：SSE 逐 token 推送，首 token 延迟 < 3s，支持 AbortController 取消
- **记忆质量控制**：蒸馏置信度分级(≥0.8 自动写入 / 0.6-0.8 用户确认 / <0.6 丢弃)
- **知识库 RAG**：PDF/DOCX/MD 文档上传 → 语义分块 → Chroma 向量检索
- **LLM 熔断降级**：DeepSeek(主) → Qwen(备)，连续失败自动切换，恢复后切回
- **Redis 会话持久化**：对话历史不丢失，自动降级纯内存模式

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY

# 2. 启动全栈
docker compose up -d

# 3. 访问
# 前端:     http://localhost:8000  (Python Agent 直连)
# Java:     http://localhost:8080
# Swagger:  http://localhost:8000/docs
```

## 本地开发

```bash
cd python-agent
pip install -r requirements.txt
python main.py
# → http://localhost:8000

# 运行测试
pytest tests/ -v
```

## 技术栈

| 层 | 技术 |
|----|------|
| AI 推理 | FastAPI · LangGraph · LangChain · Chroma |
| 大模型 | DeepSeek-V3 · 通义千问(text-embedding-v3) |
| 业务网关 | Spring Boot 3 · MyBatis-Plus · Redis · JWT |
| 前端 | 原生 JS SPA · SSE · Markdown · 暗色模式 |
| 工程化 | Docker Compose · pytest(52 用例) · ruff · GitHub Actions CI |

## 文档

- [架构设计说明书](架构设计说明书.md)
- [全阶段开发步骤](全阶段开发步骤.md)
- [调试问题记录](调试问题记录.md) — 65 条问题全记录
- [面试准备文档](面试准备文档.md) — 44 道面试问答
