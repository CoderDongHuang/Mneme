# Mneme

Mneme 是一个面向个人学习的本地优先知识库与 RAG 学习助手。你可以导入课程资料、笔记、报告和表格，围绕自己的资料提问，并查看回答引用；系统还会根据交流内容维护短期记忆、长期偏好和学习画像。

## 项目简介

Mneme 将文档检索、流式问答和三层记忆组合成一套可自行部署的学习工作台：

- 导入 PDF、DOCX、PPTX、XLSX、CSV、Markdown、TXT、HTML 等资料
- 自动解析、切分、向量化并建立可追溯引用
- 基于资料库进行问答、复习建议和内容总结
- 支持流式回答、会话历史、学习画像和记忆管理
- Java 网关负责用户、权限、文件、会话和安全策略
- Python Agent 负责 RAG、模型调用和记忆编排

本项目当前定位为**单机自部署开源版**，适合个人电脑、家庭服务器和小规模内网使用，不承诺多实例高可用或公网生产级 SLA。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 前端 | React、Vite、React Router、CSS、Playwright、Vitest |
| Java 网关 | Java 17、Spring Boot、Spring Security、JPA、Flyway、MySQL、Redis |
| Python Agent | Python 3.11、FastAPI、LangGraph、LangChain、Chroma、pytest、Ruff |
| 模型与向量 | DeepSeek、通义千问、DashScope Embedding |
| 部署 | Docker、Docker Compose、Caddy（生产可选） |

## 快速开始（Docker）

### 环境要求

- Docker Desktop（建议启用 Compose V2）
- 至少 4 GB 可用内存和 10 GB 可用磁盘
- 一个 DeepSeek 或 DashScope API Key（没有模型 Key 时无法获得真实模型回答）

### 首次启动

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少设置以下值：

```dotenv
DEEPSEEK_API_KEY=你的密钥
DASHSCOPE_API_KEY=你的密钥
SPRING_DATASOURCE_PASSWORD=本地数据库密码
JWT_SECRET=至少32字节的随机字符串
INTERNAL_SERVICE_TOKEN=至少32字节的随机字符串
```

启动基础设施和应用：

```powershell
docker compose up -d --build
```

访问 `http://localhost:5173`。停止服务：

```powershell
docker compose down
```

Windows 用户也可以执行 `start.bat`，但仍需先准备 `.env`。数据默认保存在仓库的 `data/` 目录中。

## 配置说明

### 本地部署

本地部署不需要域名、HTTPS、SMTP 或对象存储。保持以下设置即可：

```dotenv
PUBLIC_ORIGIN=localhost
PUBLIC_DOMAIN=localhost
SECURE_COOKIES=false
```

`MYSQL_ROOT_PASSWORD` 可以单独设置；未设置时 Compose 会复用 `SPRING_DATASOURCE_PASSWORD`。`INTERNAL_SERVICE_TOKEN` 和 `JWT_SECRET` 不能使用示例中的占位值。

### 公网生产

如果要让其他人通过互联网访问，请参阅 [生产部署](docs/PRODUCTION_DEPLOYMENT.md)。这时必须增加域名、HTTPS、安全 Cookie、严格 CORS、SMTP、备份策略、监控和恶意文件扫描等配置。

## 数据目录与备份

默认持久化目录：

- `data/mysql`：MySQL 数据
- `data/redis`：Redis 数据
- `data/chroma`：向量库数据
- `data/files`：用户上传文件

可使用 `scripts/backup-data.ps1` 生成备份，使用 `scripts/restore-data.ps1` 恢复。恢复前请停止应用并先复制现有 `data/` 目录；备份能否恢复应在独立目录定期演练。

## 开发与测试

开发环境、接口契约和测试命令见：

- [Docker 部署指南](docs/docker-deployment.md)
- [开发与启动](docs/development.md)
- [接口契约](docs/api.md)
- [RAG 处理流程](docs/rag.md)
- [测试说明](docs/testing.md)

CI 会执行 Java、Python 和前端测试。提交问题时请附 Docker 版本、操作系统、相关服务日志和脱敏后的配置项。

## 当前边界

- 这是单机部署版本，MySQL、Redis、Chroma 和文件存储默认使用本地卷。
- 多实例部署需要共享文件存储、独立数据库/Redis/向量服务和网关配置，当前不作为默认支持场景。
- 模型调用受外部 API 配额、网络和服务稳定性影响。
- 不要将 `.env`、用户上传文件或 `data/` 目录提交到 GitHub。

## 许可证

仓库当前未声明开源许可证。正式发布前请补充 `LICENSE` 文件，并确认模型、字体和第三方依赖的许可范围。
