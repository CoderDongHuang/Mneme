# Docker 自部署指南

本文面向从 GitHub 克隆 Mneme 后，在个人电脑运行完整系统的用户。无需购买服务器、域名、HTTPS 证书或 SMTP 服务。

## 1. 运行组件

一次 Compose 启动会运行：

| 服务 | 作用 | 宿主机端口 |
|---|---|---:|
| frontend | React 静态站点与反向代理 | 3000 |
| java-gateway | 认证、会话、资料和流式网关 | 8080 |
| python-agent | Agent、RAG 与记忆 | 8001（仅本机） |
| mysql | 业务数据 | 3306（仅本机） |
| redis | 缓存和短期状态 | 6379（仅本机） |
| chroma | 向量数据 | 8000（仅本机） |
| mailpit | 本地密码重置邮箱 | 8025（仅本机） |

正常使用只需访问 <http://localhost:3000>。

## 2. 配置与获取方式

复制配置模板：

```bash
cp .env.example .env
```

### 2.1 必须配置

```dotenv
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
MYSQL_ROOT_PASSWORD=...
SPRING_DATASOURCE_PASSWORD=...
JWT_SECRET=...
INTERNAL_SERVICE_TOKEN=...
```

`MYSQL_ROOT_PASSWORD` 与 `SPRING_DATASOURCE_PASSWORD` 应保持一致。`JWT_SECRET` 和 `INTERNAL_SERVICE_TOKEN` 至少 32 字节且互不相同。`.env` 已被 Git 忽略，不要将真实密钥提交到仓库、Issue 或日志。

#### DeepSeek API Key

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/) 并登录。
2. 在 API Keys 页面创建密钥。
3. 充值或确认账户有可用额度。
4. 填入 `DEEPSEEK_API_KEY`。

该 Key 用于意图识别、回答生成、记忆蒸馏和反思。

#### DashScope API Key

1. 打开 [阿里云百炼控制台](https://bailian.console.aliyun.com/)。
2. 开通模型服务并创建 API Key。
3. 确认 `text-embedding-v3` 可用。
4. 填入 `DASHSCOPE_API_KEY`。

该 Key 默认用于 Embedding，也用于 DeepSeek 失败后的 Qwen 备用模型。开启多模态后还会用于 Qwen-VL。

#### 本地安全密钥

PowerShell 生成 32 字节随机十六进制字符串：

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToHexString($bytes).ToLower()
```

分别执行两次，填入 `JWT_SECRET` 和 `INTERNAL_SERVICE_TOKEN`。数据库密码自行设置一个至少 16 位的随机密码。

### 2.2 文档解析配置

```dotenv
OCR_ENABLED=true
OCR_LANGUAGES=chi_sim+eng
PDF_MIN_TEXT_CHARS=80
MULTIMODAL_ENABLED=false
MULTIMODAL_MODEL=qwen-vl-plus
MULTIMODAL_MAX_IMAGES=8
```

- Docker 镜像已经内置 Tesseract、简体中文和英文语言包，不需要额外安装 OCR。
- 文本少于 `PDF_MIN_TEXT_CHARS` 的页面自动执行 OCR。
- 多模态默认关闭。只有文档包含重要图表、流程图、图片或公式时才建议开启。
- `MULTIMODAL_MAX_IMAGES` 控制单个文档最多调用的图片数量，防止额度失控。

### 2.3 本地邮件

不需要申请 SMTP。Compose 内置 Mailpit，Java 自动向 `mailpit:1025` 发信。用户点击忘记密码后，到 <http://localhost:8025> 查看验证码。

## 3. 启动与初始化

```bash
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d --build
```

首次构建需要下载镜像和依赖。服务启动后：

1. 打开 <http://localhost:3000>。
2. 注册并登录。
3. 创建资料库。
4. 上传受支持的文档并等待状态变为“可检索”。
5. 回到对话页，选择资料库后提问。

## 4. 验证服务

```bash
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml ps
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml logs -f java-gateway python-agent
```

关键地址：

- 前端：<http://localhost:3000>
- Java 健康检查：<http://localhost:8080/api/v1/health>
- Python OpenAPI：<http://localhost:8001/docs>
- 本地邮件：<http://localhost:8025>

## 5. 文档格式与 OCR

当前支持 PDF、DOCX、PPTX、XLSX/XLSM、CSV、Markdown、TXT 和 HTML。原生文本 PDF 可直接解析，表格会单独提取。

扫描型 PDF 会逐页执行 Tesseract 中文/英文 OCR。原生 PDF 使用 PyMuPDF 按版面块排序，并过滤重复页眉页脚；pdfplumber 单独提取表格。

图表、公式、图片和流程图可通过 Qwen-VL 补充解析。设置 `MULTIMODAL_ENABLED=true` 后重新创建 Python 容器：

```bash
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d --force-recreate python-agent
```

多模态结果属于模型解释，重要数字、公式和合同条款仍应通过引用原文人工核验。

## 6. 数据与升级

持久化目录：

```text
data/mysql
data/redis
data/chroma
data/files
```

升级前先执行备份脚本，再拉取代码并重建：

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d --build
```

数据库结构由 Flyway 自动迁移。跨大版本升级前应阅读 Release Notes 并保留可恢复备份。

## 7. 常见问题

### 页面可以打开，但接口连接失败

检查 `java-gateway` 是否运行，并查看其日志。前端容器通过 Caddy 将 `/api/*` 转发给 Java。

### 文档一直处于解析中或解析失败

同时查看 Java 和 Python 日志；确认文件格式受支持、文件未损坏、模型 Key 有效，并确认 Chroma 可用。

### 回答没有引用资料

确认文档状态为“可检索”、对话页选中了对应资料库，并尝试使用文档中的具体关键词提问。资料片段不足时，Agent 会明确说明并使用通用知识补充。

### 模型调用失败

检查 API Key、账户余额和网络访问。DeepSeek 不可用时，仅在 DashScope Key 有效且备用模型开启的情况下切换到 Qwen。

### 忘记密码没有收到邮件

打开 <http://localhost:8025> 查看 Mailpit。若没有邮件，执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml logs java-gateway mailpit
```

Mailpit 只在本机保存邮件，不会投递到真实邮箱。

## 8. 本地验收

```bash
# OCR 语言包
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml exec python-agent tesseract --list-langs

# 离线 RAG 指标，不消耗模型额度
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml exec -e MNEME_OFFLINE_EMBEDDINGS=true python-agent python scripts/evaluate_rag.py

# 真实模型全链路，会发送 test-fixtures/rag-fixture.txt 并消耗少量额度
cd frontend
MNEME_REAL_E2E=true MNEME_E2E_BASE_URL=http://127.0.0.1:3000 npm run test:e2e:real
```

Windows PowerShell 的真实 E2E：

```powershell
$env:MNEME_REAL_E2E='true'
$env:MNEME_E2E_BASE_URL='http://127.0.0.1:3000'
npm run test:e2e:real
```

## 9. 停止与清理

```bash
# 停止，保留数据
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml down

# 查看磁盘使用
docker system df
```

删除 `data/` 会永久删除本地业务与向量数据，请先备份。
