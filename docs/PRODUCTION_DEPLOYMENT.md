# 生产部署基线

生产环境使用 `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`。上线前必须配置公网域名、HTTPS、SMTP、管理员令牌、模型额度以及独立随机密钥。

## 数据与扩展

- MySQL、Redis 和 Chroma 应使用独立托管实例或持久化卷，定期做快照。
- 多主机部署时，`FILE_STORAGE_PATH` 必须指向所有 Java 和 Python 实例都可访问的共享卷，例如 NFS、云文件系统或挂载后的对象存储网关。
- Java 限流状态存储在 Redis，可以水平扩展；Python 会话存储使用 Redis，向量服务使用独立 Chroma HTTP 服务。
- Python 轨迹和记忆版本的辅助状态使用 `AUXILIARY_STORE_BACKEND=mysql` 写入共享 MySQL；SQLite 仅用于单机开发和迁移兼容。SQLite 词法索引是可重建的派生数据，多实例部署应使用一致的共享索引卷或在发布后重建。
- 文件处理任务具有幂等键，可启动多个任务消费者，但同一文档只允许一个任务成功提交。

## 安全

- `SECURE_COOKIES=true`，`CORS_ORIGINS` 只能填写正式站点域名。
- 配置 SMTP 后密码重置验证码才可发送，令牌有效期 15 分钟且只能使用一次。
- `ADMIN_API_TOKEN` 至少 32 字节，仅通过密钥管理服务注入。
- 建议在 Caddy 前增加云防火墙和上传文件恶意软件扫描服务。当前内置校验负责大小、扩展名、文件头和可执行文件拦截。

## 备份恢复

统一工具会先停止写入服务，再创建 MySQL、原文件、头像、Chroma、内置 MinIO 和 Python SQLite/会话状态的一致快照。归档内的版本化 `manifest.json` 记录每个文件的大小和 SHA-256；恢复前会拒绝校验失败、缺项、未知文件、链接和路径穿越。

```powershell
python scripts/backup_restore.py backup --output-dir backups
python scripts/backup_restore.py verify backups/mneme-YYYYMMDD-HHMMSS.tar.gz
python scripts/backup_restore.py restore backups/mneme-YYYYMMDD-HHMMSS.tar.gz --yes --report backups/restore-report.json
```

PowerShell 可继续使用 `scripts/backup-data.ps1` 和 `scripts/restore-data.ps1 -Archive <path> -Force`，Shell 使用 `scripts/backup.sh`，它们均调用同一个 Python 实现，不再维护独立恢复逻辑或固定数据库密码。

执行恢复的系统用户必须对 `data/files`、`data/avatars`、`data/chroma`、`data/minio` 和 `python-agent/data` 拥有读写权限。Linux 部署应让容器与备份进程使用一致 UID/GID，或由受控的运维账号执行恢复；不要长期将数据目录设为全局可写。

每天创建备份并同步到异地不可变存储；每月至少在隔离环境恢复一次。`restore-report.json` 记录本次 RPO（备份创建至恢复完成的时间）和 RTO（恢复执行耗时），应纳入 SLO 审查。使用外部 S3 而非内置 MinIO 时，还必须通过供应商快照或版本化复制独立备份对象桶；本工具只能直接归档本机 `data/minio`。

## SLO、告警与灾备演练

Prometheus 和 Alertmanager 可通过 `docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.observability.yml up -d` 启动。目标值、记录规则和告警位于 `observability/slo.json` 与 `observability/prometheus/`；应用错误率、可用性和 p95 延迟进入统一告警。默认接收器在 Alertmanager 中保留告警状态；正式部署必须在 `observability/alertmanager.yml` 增加组织实际使用的邮件、Webhook 或值班平台接收器。

每月 GitHub Actions 会在隔离栈执行备份、删除、恢复和恢复后 RAG 验证，上传 90 天证据。变更前也可手动运行 `Disaster recovery and SLO evidence`，不能以“备份文件存在”替代恢复演练。
