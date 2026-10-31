# 生产部署基线

生产环境使用 `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build`。上线前必须配置公网域名、HTTPS、SMTP、管理员令牌、模型额度以及独立随机密钥。

## 固定发布镜像

基础配置与自托管发行版均从镜像加载代码，只挂载数据；Python 的 `python-agent/data:/app/data` 保留原有 SQLite、会话与上传目录，备份路径不变。生产必须设置 `MNEME_PYTHON_IMAGE`、`MNEME_JAVA_IMAGE`、`MNEME_FRONTEND_IMAGE`，使用每次发布唯一的版本标签，优先选择 `registry/repository@sha256:<64位摘要>`，禁止空值、无标签或 latest。标签应在镜像仓库设为不可覆盖。首次切换前先按下文创建并验证备份。

在受信任的发布环境从已测试提交分别构建并发布三个镜像；前端使用仓库根目录作为 context，Dockerfile 为 `frontend/Dockerfile`。将三个实际镜像引用写入部署环境后执行：

```bash
python scripts/verify_immutable_images.py --production
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build
```

宿主源码变更不会进入运行容器。升级需先完成测试、构建、发布，再更新镜像引用并重新创建服务；只执行 restart 不会升级镜像。回滚需保留旧镜像引用，并评估数据库迁移是否允许旧程序读取，必要时恢复匹配备份。不要将 `docker-compose.dev.yml` 加入生产命令；它仅用于本地挂载源码和自动 reload。

`python scripts/verify_immutable_images.py` 在独立临时镜像/容器中用实际 Python Dockerfile 验证宿主源码变更不影响已构建代码，并验证密钥文件和本地数据未进入镜像；不访问当前项目数据库，也不重建运行服务。

## 数据与扩展

- MySQL、Redis 和 Qdrant 应使用独立托管实例或持久化卷，定期做快照。
- 多主机部署时，`FILE_STORAGE_PATH` 必须指向所有 Java 和 Python 实例都可访问的共享卷，例如 NFS、云文件系统或挂载后的对象存储网关。
- Java 限流状态存储在 Redis，可以水平扩展；Python 会话存储使用 Redis，向量服务使用独立 Qdrant HTTP 服务。
- Python 轨迹和记忆版本的辅助状态使用 `AUXILIARY_STORE_BACKEND=mysql` 写入共享 MySQL；SQLite 仅用于单机开发和迁移兼容。SQLite 词法索引是可重建的派生数据，多实例部署应使用一致的共享索引卷或在发布后重建。
- 文件处理任务具有幂等键，可启动多个任务消费者，但同一文档只允许一个任务成功提交。

## 安全

- `SECURE_COOKIES=true`，`CORS_ORIGINS` 只能填写正式站点域名。
- 配置 SMTP 后密码重置验证码才可发送，令牌有效期 15 分钟且只能使用一次。
- `ADMIN_API_TOKEN` 至少 32 字节，仅通过密钥管理服务注入。
- 建议在 Caddy 前增加云防火墙和上传文件恶意软件扫描服务。当前内置校验负责大小、扩展名、文件头和可执行文件拦截。

### 密码重置邮件

生产基础配置不启动 Mailpit。设置 `SPRING_MAIL_HOST`、`SPRING_MAIL_PORT`（默认 587）、`SPRING_MAIL_USERNAME`、`SPRING_MAIL_PASSWORD`、`PASSWORD_RESET_FROM`，并保留 `SPRING_MAIL_PROPERTIES_MAIL_SMTP_AUTH=true` 和 `SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_ENABLE=true`。启用 STARTTLS 时同时要求协商成功，避免静默降级；使用供应商允许的发件人。连接、读取和写入超时各为 5 秒。不要启用 JavaMail debug 或记录邮件正文。

本地使用 `docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d`，该覆盖文件显式选择 Mailpit、1025 端口和本地发件人。收件箱地址为 `http://localhost:8025`。Mailpit 不会向公网邮箱转发邮件。

上线验收：注册专用测试账号，在个人资料中配置测试邮箱，触发忘记密码，在运营方真实邮箱中检查收信并完成重置；验证原密码失效、验证码只能用一次。运维页区分“邮件服务未配置”、配置完成、最近投递失败和“SMTP 已接收”；最后一项仅证明当前网关的 SMTP 服务器接收，不保证终端邮箱收信。未配置或投递异常返回 503，不返回发送成功；响应和应用日志不附带底层邮件异常、完整收件地址或验证码。最近投递状态只属于当前网关进程，重启后恢复为尚未尝试，多实例应分别检查。

## 备份恢复

### Redis 认证与持久化

生产必须设置非空 `REDIS_PASSWORD`；同一变量供 Redis 服务器、Java 和 Python 使用。仅本地开发、自托管本机和离线演示允许空密码，端口只绑定回环地址。Redis 启用 `appendonly yes`、`appendfsync everysec`，客户端启动前等待带认证的 PING 健康检查。不要将 Redis 暴露到公网。

AOF 每秒同步意味着异常掉电时仍可能丢失约一秒内尚未落盘的写入，不提供零 RPO 保证。反思任务必须写入 Redis Stream，Redis 不可用时返回失败且不回退内存队列；Agent 就绪检查返回 503，并分别展示 `reflection_queue=unavailable_no_memory_fallback` 与可降级的会话缓存状态。恢复 Redis 后就绪检查自动恢复，pending 任务由 consumer group 接管重试。

下述统一备份工具停写并停止 Redis 后归档完整 `data/redis`，包含 `appendonlydir` 的 manifest、base 和 incremental 文件及存在的 RDB。恢复必须整体恢复该目录及匹配的应用数据库，不能只复制 `dump.rdb` 或单个 AOF 片段；Redis 同时存在两者时优先加载 AOF。密钥通过独立密钥管理恢复，不写入归档。每次演练检查 AUTH/PING、AOF 配置和 Stream pending 消费恢复。

可运行 `python scripts/verify_redis_durability.py`，在独立容器、网络和临时卷验证空密码、密码认证、AOF fsync 后 SIGKILL 及 pending 任务恢复；它不会访问现有项目 Redis 数据。

统一工具会先停止写入服务和 Redis，再创建 MySQL、Redis 持久化目录（含待处理反思 Stream）、原文件、头像、Qdrant、内置 MinIO 和 Python SQLite/会话状态的一致快照。归档内的版本化 `manifest.json` 记录每个文件的大小和 SHA-256；恢复前会拒绝校验失败、缺项、未知文件、链接和路径穿越。

```powershell
python scripts/backup_restore.py backup --output-dir backups
python scripts/backup_restore.py verify backups/mneme-YYYYMMDD-HHMMSS.tar.gz
python scripts/backup_restore.py restore backups/mneme-YYYYMMDD-HHMMSS.tar.gz --yes --report backups/restore-report.json
```

PowerShell 可继续使用 `scripts/backup-data.ps1` 和 `scripts/restore-data.ps1 -Archive <path> -Force`，Shell 使用 `scripts/backup.sh`，它们均调用同一个 Python 实现，不再维护独立恢复逻辑或固定数据库密码。

执行恢复的系统用户必须对 `data/files`、`data/avatars`、`data/qdrant`、`data/redis`、`data/minio` 和 `python-agent/data` 拥有读写权限。Linux 部署应让容器与备份进程使用一致 UID/GID，或由受控的运维账号执行恢复；不要长期将数据目录设为全局可写。

每天创建备份并同步到异地不可变存储；每月至少在隔离环境恢复一次。`restore-report.json` 记录本次 RPO（备份创建至恢复完成的时间）和 RTO（恢复执行耗时），应纳入 SLO 审查。使用外部 S3 而非内置 MinIO 时，还必须通过供应商快照或版本化复制独立备份对象桶；本工具只能直接归档本机 `data/minio`。

## SLO、告警与灾备演练

Prometheus 和 Alertmanager 可通过 `docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.observability.yml up -d` 启动。目标值、记录规则和告警位于 `observability/slo.json` 与 `observability/prometheus/`；应用错误率、可用性和 p95 延迟进入统一告警。启动 Alertmanager 前，必须在部署主机的环境中设置有效 HTTP(S) `ALERTMANAGER_WEBHOOK_URL`，运行 `python scripts/render_alertmanager_config.py`，再执行 Compose 命令。生成的 `data/alertmanager/alertmanager.yml` 包含通知地址（可能含令牌），已被 Git 忽略；应限制数据目录的主机访问权限，勿上传为日志或 artifact。更新地址后重新生成并重启 Alertmanager。模板 `observability/alertmanager.yml` 不直接作为容器配置使用；未生成配置时 Alertmanager 应启动失败，不会静默丢失通知。

### 向量存储升级

当前固定 Qdrant 服务与客户端 1.20.0；旧 Chroma 数据不能直接挂入 Qdrant。先按[迁移指南](VECTOR_STORE_MIGRATION.md)停写、导出、迁入空目标并逐条验证。保留原始数据与匹配的整栈备份，禁止通过删除旧目录绕过启动保护。

每月 GitHub Actions 会在隔离栈执行备份、删除、恢复和恢复后 RAG 验证，上传 90 天证据。变更前也可手动运行 `Disaster recovery and SLO evidence`，不能以“备份文件存在”替代恢复演练。
