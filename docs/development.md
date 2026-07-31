# 开发与启动

## 本地工具链

- Python 3.11
- Java 17、Maven 3.9+
- Node.js 22、npm 10+
- Docker Desktop（用于 MySQL、Redis、Chroma）

## Docker 启动

从仓库根目录复制 `.env.example` 为 `.env`，填写模型 Key、数据库密码、JWT_SECRET 和 INTERNAL_SERVICE_TOKEN，然后执行：

```powershell
docker compose up -d --build
```

查看状态：`docker compose ps`；查看日志：`docker compose logs -f java-gateway python-agent`。

## 源码开发启动

```powershell
docker compose up -d mysql redis chroma
cd python-agent; python main.py
cd ..\java-gateway; mvn clean spring-boot:run
cd ..\frontend; npm install; npm run dev
```

Windows 下也可运行根目录 `start.bat`。停止基础设施：`docker compose down`。

## 常见问题

- Python 健康检查在 `http://localhost:8001/health`，`8000` 是 Chroma 端口。
- Java 无法启动时，检查 MySQL 健康状态以及 `.env` 中的数据库密码是否一致。
- 没有模型 Key 时只能验证基础接口，无法完成真实模型问答。
- OCR 需要额外安装 Tesseract；关闭 OCR 可设置 `OCR_ENABLED=false`。
