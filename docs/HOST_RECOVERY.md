# 宿主机整站备份与恢复

个人归档恢复只为当前用户新增副本；整站恢复覆盖整个部署。管理员网页现在同时提供 GitHub 隔离演练和宿主机实际恢复，两者是独立入口。默认未启用宿主机执行器，页面会显示配置说明。

## 配置

执行器必须运行在 Docker 宿主机，拥有该项目目录和 Docker Compose 权限，不能放在恢复时会停止的网关容器中。使用 Python 3.10+，安装 `cryptography`、`python-dotenv`（也可使用项目锁文件）。在项目 `.env` 设置：

```dotenv
RECOVERY_WORKER_URL=http://host.docker.internal:8091
RECOVERY_WORKER_TOKEN=<独立随机密钥，至少32字符>
ADMIN_API_TOKEN=<另一独立随机密钥，至少32字符>
MODEL_CONFIG_ENCRYPTION_KEY=<稳定的独立随机密钥，至少32字符>
BACKUP_ENCRYPTION_KEY=<备份加密密钥>
BACKUP_SIGNING_KEY=<独立备份签名密钥>
BACKUP_KEY_VERSION=v1
BACKUP_REQUIRE_PROTECTION=true
```

不要使用示例占位符。`backup_restore.py` 自动读取项目 `.env`；保留这些秘密的独立安全副本。个人模型配置在 MySQL 中以 AES-GCM 加密并绑定用户 ID，密钥留空时回退到 JWT_SECRET；改变实际加密密钥后原密文不能解密，应先完成受控迁移或让用户重新保存个人配置。

Linux 给网关添加 `extra_hosts: ["host.docker.internal:host-gateway"]`（CI 覆盖文件已有）。Docker Desktop 支持该主机名。使用防火墙限制执行器只供 Docker 私有网络访问，勿将 8091 暴露到公网。

```bash
python scripts/recovery_worker.py --host 0.0.0.0 --port 8091 \
  --compose-file docker-compose.yml --compose-file docker-compose.selfhost.yml
```

默认监听 127.0.0.1；上例显式允许容器访问。生产环境请用宿主机服务管理器运行并设置自动启动，保留任务目录、日志和备份。更新配置后重建网关。用户账号必须为 active admin，同时输入管理员凭证，才能操作整站备份；宿主机另行验证独立恢复令牌。

## 操作与失败处理

1. 在“备份与恢复 → 管理员整站灾备”创建备份，输入 `BACKUP SITE`。备份期间停止相关服务，完成后启动。
2. 选择备份并验证清单、哈希、备份格式及 Flyway 兼容性，查看覆盖和保留范围。
3. 核对 SHA-256 后输入 `RESTORE SITE`。服务会停止；页面暂时断开属预期，恢复后重新登录并刷新任务历史。
4. 恢复前先创建并验证检查点；应用失败时回滚。回滚失败则保持服务停止，操作员检查 `backups/jobs/*.log` 和 `.report` 后处理，不能直接重开流量。
5. 验证登录、原文、向量检索、问答与引用后再恢复对外流量。任务成功表示恢复脚本通过，不等于任意业务数据都已人工验收。

覆盖范围包含 MySQL、Redis、文件、头像、Qdrant、对象存储本地卷及 Agent 数据；`.env`、部署配置、加密密钥与备份归档保留。使用远端对象存储或异地 KMS 的生产恢复仍须遵循其专门部署流程，见 [灾备说明](cloud-recovery.md)。保留期清理不由网页自动执行。

执行器同一时刻只接受一个操作；只接受固定动作和备份目录内的普通归档，拒绝外部路径、符号链接、任意命令和预览后变更的摘要。服务重启后未完成任务标为 interrupted，不自动重放危险操作。

## 可复现验收

仅在可丢弃、使用独立卷/目录的测试栈运行：

```bash
python scripts/verify_site_recovery.py --confirm-disposable-stack \
  --compose-file docker-compose.yml --compose-file docker-compose.selfhost.yml
```

需要网关配置上述 URL 与令牌；测试会创建账号、入库、备份、删除测试账号，再恢复整站。报告位于 `backups/worker-acceptance/acceptance.json`。本机已在独立 `mneme-review-recovery` 栈验证权限、摘要拒绝、跨存储删除、恢复后登录/原文/向量/带引用问答及回滚检查点。不要对正在使用的数据库运行这一破坏性验收脚本。
