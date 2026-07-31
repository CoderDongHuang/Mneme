# Docker 部署指南

## 适用范围

本文面向希望直接运行 Mneme 的开源用户。默认是单机部署：所有数据库、向量库和上传文件都保存在本机 Docker 挂载目录，不需要域名或公网服务。

## 准备工作

安装 Docker Desktop，并确认命令可用：

```powershell
docker --version
docker compose version
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中设置模型 Key、数据库密码和两个随机服务密钥。随机密钥至少 32 字节，不能使用模板占位文本。

## 启动与验证

```powershell
docker compose up -d --build
docker compose ps
```

打开 `http://localhost:5173`，注册账号后上传资料并等待解析完成。服务检查地址：

- Java：`http://localhost:8080/api/v1/health`
- Python：`http://localhost:8001/health`
- Chroma：`http://localhost:8000/api/v1/heartbeat`

查看日志：`docker compose logs -f java-gateway python-agent`。

## 数据和升级

数据位于 `data/mysql`、`data/redis`、`data/chroma` 和 `data/files`。升级代码前先备份，升级后执行：

```powershell
docker compose pull
docker compose up -d --build
```

不要删除 `data/`，否则会丢失数据库、向量索引和上传文件。

## 备份与恢复

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backup-data.ps1
powershell -ExecutionPolicy Bypass -File scripts/restore-data.ps1 -BackupPath <备份目录>
```

恢复前停止服务并复制当前 `data/` 目录。建议定期在另一份目录演练恢复，而不是只检查备份文件是否存在。

## 停止和清理

```powershell
docker compose down
```

此命令不会删除持久化数据。只有确认不再需要本地数据时，才手动删除 `data/`。

## 公网部署

公网部署需要额外配置域名、HTTPS、`SECURE_COOKIES=true`、严格 CORS、SMTP、异地备份、监控和文件恶意扫描。请阅读 [公网生产部署](PRODUCTION_DEPLOYMENT.md)，不要直接把本地配置暴露到互联网。
