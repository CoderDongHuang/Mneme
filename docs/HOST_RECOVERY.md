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

不要使用示例占位符。`backup_restore.py` 自动读取项目 `.env`；保留这些秘密的独立安全副本。个人模型配置在 MySQL 中以 AES-GCM 加密并绑定用户 ID 与密钥版本。生产环境强制独立 MODEL_CONFIG_ENCRYPTION_KEY，仅开发环境允许空密钥回退 JWT_SECRET。轮换时保留所需旧版本密钥并完成受控迁移；备份恢复前会核验密钥版本覆盖。

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

## 离线文档与对象留存

`python scripts/maintain_retention.py` 默认只读，输出候选版本、任务、对象、缓存与字节数。工具使用指定 Gateway 容器的实际镜像、数据库配置、网络与文件挂载，不启动应用、迁移或调度器。必须先部署包含 `com.mneme.maintenance.RetentionMain` 的新镜像。

策略 JSON（`--policy` 指定）默认保留最新 10 版；仅同时超出最新数量且超过 30 天的版本可回收。当前文档原件、未移除任务 payload 的 `file_path/file_paths` 和 `pinned_locations` 引用始终保留；最高版本号保留以保证后续上传编号递增。仅回收超过 30 天、非文档当前解析任务的 completed/cancelled 任务，失败任务保留供重试。无引用原件有 24 小时宽限；缓存默认 24 小时或 1 GiB 容量阈值。数量、天数和小时须为正整数，缓存字节可为零。

```json
{"versions":10,"version_days":30,"task_days":30,"orphan_hours":24,"cache_hours":24,"cache_bytes":1073741824,"pinned_locations":[]}
```

完整备份包含原件副本时，无需为其钉住在线对象。仅保存引用的外部归档必须把仍需恢复的位置放入 `pinned_locations`；工具不会猜测外部依赖。未知文件名和链接不作为清理候选，损坏/中断清单会阻止执行。全量盘点需要与当前对象数相应的内存和时间，大库先在隔离副本评估。

本地执行流程（先预览并核对空间；备份还会暂存一份未压缩数据）：

```powershell
python scripts/maintain_retention.py --container mneme-java-gateway-1
python scripts/backup_restore.py --compose-file docker-compose.yml --compose-file docker-compose.selfhost.yml backup --output-dir backups --keep-stopped
# 将下方路径替换为上一条实际输出的归档；若有引用型备份，同时传 --policy 实际策略文件。
python scripts/maintain_retention.py --container mneme-java-gateway-1 --recovery-archive backups/mneme-YYYYMMDD-HHMMSS.tar.gz --apply
```

`--keep-stopped` 在成功和失败时都保持应用写入者停止，备份失败必须先查明原因。执行前工具重新核验归档格式/哈希/迁移版本、当前 SQL 和所有托管本地原件；有其他 Gateway、Agent 或共享目录写入者、备份过期/缺原件时拒绝删除。禁止在此期间手工写库。每次执行重新生成计划；执行改变 SQL 后再次执行必须重新备份，旧归档不能授权删除。SQL 元数据事务先提交，再删除对象；文件删除失败时留下可重新盘点的孤儿，不报告成功。

结束后按原部署配置先恢复 Redis/Qdrant/对象存储，再 Agent、最后 Gateway，核验健康、旧版预览及新上传；使用已有容器可依次 `docker start`，避免用不匹配的 Compose 配置重建。若需要回退，走上文完整恢复流程，保留本次匹配备份，不能只回滚 SQL。

S3 当前支持只读计划；普通宿主备份无法证明远端原件的恢复覆盖，`--apply` 会拒绝。该工具尚不清理旧 OCR 临时目录、长期活跃会话回执、记忆检查点、备份归档或 SQLite WAL，不代表完整 P2-12 已完成，也不会由网页自动执行。当前 OCR 已改用内存管道，避免新增识别图片/文本/坐标临时文件；旧残片与上传孤儿的边界见 [OCR 管道](INDEX_GENERATIONS.md#ocr-管道与处理时限)。

## 上传临时文件回收

`python scripts/maintain_uploads.py` 默认只读计划，报告候选文件数、字节数、近期保留数和未知项数，不输出文件名或正文。默认保留 24 小时，可用正整数 `--hours` 调整。必须先部署包含 `app.storage.upload_maintenance` 的 Agent 镜像；工具从实际容器读取镜像、挂载与 `UPLOAD_DIR`，要求目录在可写持久挂载中。

```powershell
python scripts/maintain_uploads.py --container mneme-python-agent-1
# 停止全部 Gateway、Agent 副本及其他共享目录写入者，再执行：
python scripts/maintain_uploads.py --container mneme-python-agent-1 --hours 24 --apply
# 按原部署顺序恢复 Agent、Gateway，并核验健康、现有原文与新上传。
```

工具只扫描 `UPLOAD_DIR/.mneme-staging` 的直接子文件，回收严格匹配受管名称、超过保留期的普通文件；保留近期文件、未知文件和子目录，不递归。链接、硬链接、Windows junction、盘点后变更或目录错误会使执行失败。执行前验证全部候选，再逐文件重验；部分文件删除后遇到故障则报告失败，可重新计划并重跑。执行使用宿主维护锁、实际镜像和挂载，并拒绝运行中的同项目写入者或共享目录容器；禁止维护期间手工启动服务或写入目录。

该目录专供可丢弃的异步上传副本，不能放原件或引用型备份。此工具不删除业务版本和持久任务原件，无须用整站备份证明这些临时副本的可丢弃性；业务原件留存仍遵循上一节的备份门禁。更早版本的系统临时目录残片、旧 OCR 文件不在此工具范围，无法确认归属时保留。保留期本身不证明任务已结束，因此不提供在线自动执行。

## 整站恢复验收

仅在可丢弃、使用独立卷/目录的测试栈运行：

```bash
python scripts/verify_site_recovery.py --confirm-disposable-stack \
  --compose-file docker-compose.yml --compose-file docker-compose.selfhost.yml
```

需要网关配置上述 URL 与令牌；测试会创建账号、入库、备份、删除测试账号，再恢复整站。报告位于 `backups/worker-acceptance/acceptance.json`。本机已在独立 `mneme-review-recovery` 栈验证权限、摘要拒绝、跨存储删除、恢复后登录/原文/向量/带引用问答及回滚检查点。不要对正在使用的数据库运行这一破坏性验收脚本。
