# 生产部署基线

生产环境使用 `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`。上线前必须配置公网域名、HTTPS、SMTP、管理员令牌、模型额度以及独立随机密钥。

## 数据与扩展

- MySQL、Redis 和 Chroma 应使用独立托管实例或持久化卷，定期做快照。
- 多主机部署时，`FILE_STORAGE_PATH` 必须指向所有 Java 和 Python 实例都可访问的共享卷，例如 NFS、云文件系统或挂载后的对象存储网关。
- Java 限流状态存储在 Redis，可以水平扩展；Python 会话存储使用 Redis，向量服务使用独立 Chroma HTTP 服务。
- 文件处理任务具有幂等键，可启动多个任务消费者，但同一文档只允许一个任务成功提交。

## 安全

- `SECURE_COOKIES=true`，`CORS_ORIGINS` 只能填写正式站点域名。
- 配置 SMTP 后密码重置验证码才可发送，令牌有效期 15 分钟且只能使用一次。
- `ADMIN_API_TOKEN` 至少 32 字节，仅通过密钥管理服务注入。
- 建议在 Caddy 前增加云防火墙和上传文件恶意软件扫描服务。当前内置校验负责大小、扩展名、文件头和可执行文件拦截。

## 备份恢复

每天运行 `scripts/backup-data.ps1`，将结果同步到异地对象存储。每月至少在隔离环境运行一次 `scripts/restore-data.ps1`，验证数据库和文件快照可以恢复。
