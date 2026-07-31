# 开发与启动

## 环境要求

- Python 3.11
- Java 17、Maven 3.9+
- Node.js 22、npm 10+
- Docker Desktop（推荐用于 MySQL、Redis、Chroma）

## 首次安装

```powershell
cd python-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd ..\java-gateway
mvn dependency:go-offline

cd ..\frontend
npm install
```

## 启动顺序

1. `docker compose up -d mysql redis chroma`
2. `cd python-agent && python main.py`
3. `cd java-gateway && mvn clean spring-boot:run`
4. `cd frontend && npm run dev`

也可以运行根目录 `start.bat` 打开三个独立终端。

## 常见问题

- `localhost:8000/health` 返回 404：8000 是 Chroma，Python 健康检查在 8001。
- Java 启动失败：先确认 MySQL 已创建 `mneme` 数据库，密码与 `.env`/环境变量一致。
- Redis 认证失败：配置 `REDIS_PASSWORD`；Redis 是可选依赖，失败不会阻止 Python 启动。
- PDF 无内容：扫描件需要系统安装 Tesseract，并设置 `OCR_ENABLED=true`。
- 依赖冲突：必须在独立虚拟环境安装 `python-agent/requirements.txt`，不要复用装有其他 AI 项目的全局 Python。
