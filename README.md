# Mneme

Mneme 是一个具备三级记忆的个人学习助手。用户可以上传课件、笔记、简历、报告等资料，Agent 会基于资料回答并给出可追溯引用，同时逐步形成用户的表达偏好、知识薄弱点和学习进度。

## 核心能力

- **结构化 RAG**：支持 PDF、DOCX、PPTX、XLSX、CSV、Markdown、TXT 和 HTML，保留文档、页码、章节与内容类型元数据。
- **Agent 决策链**：LangGraph 编排 `qa / review / suggest / general` 四类意图及条件检索、推理和记忆回写。
- **三级记忆**：工作记忆负责当前窗口，短期记忆负责跨轮历史与摘要，长期记忆负责偏好、薄弱点和进度。
- **流式回答**：Python 逐 token 生成 SSE，Java Gateway 原样转发，前端实时渲染并展示引用。
- **记忆质量控制**：高置信度自动写入，中置信度由用户确认，低置信度直接丢弃。
- **模型容错**：DeepSeek 为主模型，Qwen 为备用模型，支持失败切换和熔断恢复。

## 系统边界

```text
React :5173
  -> Java Gateway :8080
       -> MySQL: 用户、资料元数据、会话与消息
       -> Redis: 可选热点缓存
       -> Python Agent :8001
            -> LangGraph / RAG / 三级记忆
            -> Chroma :8000 或本地持久化目录
            -> DeepSeek / DashScope
```

浏览器只访问 Java Gateway。Python Agent 是内部推理服务，不承担用户认证和业务数据主存储。

## 本地启动

### 1. 准备配置

```powershell
Copy-Item .env.example .env
```

至少配置：

```dotenv
DEEPSEEK_API_KEY=你的密钥
DASHSCOPE_API_KEY=你的密钥
SPRING_DATASOURCE_PASSWORD=你的 MySQL 密码
JWT_SECRET=至少32字节的随机字符串
```

### 2. 准备基础设施

```powershell
docker compose up -d mysql redis chroma
```

### 3. 启动三个应用

直接运行根目录的 `start.bat`，或分别启动：

```powershell
cd python-agent
python main.py

cd java-gateway
mvn clean spring-boot:run

cd frontend
npm install
npm run dev
```

访问地址：

- 前端：<http://localhost:5173>
- Java 健康检查：<http://localhost:8080/api/v1/health>
- Python 文档：<http://localhost:8001/docs>
- Chroma：<http://localhost:8000>

## 验证

```powershell
cd python-agent
ruff check .
python -m pytest tests -q

cd ../java-gateway
mvn test

cd ../frontend
npm run build
```

## 文档

- [架构设计说明书](架构设计说明书.md)
- [开发与启动](docs/development.md)
- [接口契约](docs/api.md)
- [文档解析与 RAG](docs/rag.md)
- [前端设计](docs/frontend.md)
- [测试说明](docs/testing.md)

`全阶段开发步骤.md`、`调试问题记录.md` 为历史过程记录，不作为当前实现依据。
