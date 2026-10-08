# 开发与启动

## 环境要求

- Python 3.11
- Java 17、Maven 3.9+
- Node.js 22、npm 10+
- Docker Desktop（推荐用于 MySQL、Redis、Chroma）

首次运行前先检查项目本地工具、缓存写权限和 Docker 配置：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_environment.ps1
```

## 首次安装

```powershell
cd python-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Windows CPython 3.11: platform-specific wheels and hashes
pip install --require-hashes -r requirements.windows.lock
# Linux/Docker CPython 3.11 uses requirements.lock instead.

cd ..\java-gateway
mvn dependency:go-offline

cd ..\frontend
npm ci
```

## 启动顺序

1. `docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d mysql redis chroma`
2. `cd python-agent && python main.py`
3. `cd java-gateway && mvn clean spring-boot:run`
4. `cd frontend && npm run dev`

也可以运行根目录 `start.bat` 打开三个独立终端。

原生 Python 开发默认 `CHROMA_MODE=local`，使用本地持久化客户端；Compose 中的 Chroma 仅供容器内 Python 访问，不发布宿主机端口。若从宿主机连接远端 Chroma，应单独配置受控地址，不要把默认隔离网络暴露到公网。

## 常见问题

- `localhost:8000/health` 返回 404：8000 是 Chroma，Python 健康检查在 8001。
- Java 启动失败：先确认 MySQL 已创建 `mneme` 数据库，密码与 `.env`/环境变量一致。
- Java 测试临时目录：Surefire 默认使用 `java-gateway/target`，避免 Windows 隔离账户无法访问用户临时目录；若使用自定义 Maven 配置，请保留该项目内临时目录设置。
- Redis 认证失败：检查 `REDIS_PASSWORD` 和服务状态。完整工作流的限流、短期状态和反思队列依赖 Redis；Python 局部降级不代表完整部署可省略 Redis。
- PDF 无内容：扫描件需要系统安装 Tesseract，并设置 `OCR_ENABLED=true`。
- 依赖冲突：必须在独立虚拟环境安装依赖，不要复用装有其他 AI 项目的全局 Python。CI/Docker 使用 Linux CPython 3.11 的 `requirements.lock`；升级依赖时先修改 `requirements.txt`，重新生成并验证对应平台锁文件。
- 依赖锁文件：Windows 使用 `requirements.windows.lock`，Linux/Docker 使用 `requirements.lock`。平台 wheel 的哈希不同，不能把一个平台的哈希复制到另一个锁文件；更新依赖后运行 `python scripts/generate_windows_requirements_lock.py`，再分别执行两个平台的 `pip install --require-hashes` 和 `pip-audit`。
- 真实栈入口：运行 `python scripts/run_real_stack_e2e.py --config-only` 只校验 Compose；运行不带该参数的命令会构建、健康检查、执行真实浏览器验收，失败时自动输出服务状态和日志并清理容器。调试时可加 `--keep`。
