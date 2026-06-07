# Mneme - 个人学习助手

基于三级记忆架构的个人学习助手Agent，让AI"记住你、了解你、主动帮你"。

## 架构

- **Python Agent层**: LangGraph + Chroma + DeepSeek/通义千问
- **Java Gateway层**: Spring Boot 3 + MyBatis-Plus + Redis
- **部署**: Docker Compose 一键启动

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 2. 启动服务
docker-compose up -d

# 3. 访问服务
# Java Gateway: http://localhost:8080
# Python Agent: http://localhost:8001
```

## 技术栈

| 层级 | 技术 |
|------|------|
| Python | FastAPI, LangGraph, Chroma, LangChain |
| Java | Spring Boot 3, MyBatis-Plus, Redis, JWT |
| 基础设施 | MySQL 8.0, Redis 7, Chroma |

## 文档

- [架构设计说明书](架构设计说明书.md)
- [全阶段开发步骤](全阶段开发步骤.md)
