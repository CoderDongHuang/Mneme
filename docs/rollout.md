# 升级、验收与回退

本页适用于当前 Beta 自部署版本。历史 V3 迁移步骤已经过期；数据库以 `java-gateway/src/main/resources/db/migration` 中的 Flyway 迁移为准，当前最高版本为 V20（文档标签与版本解析报告；V19 为文档解析报告）。

## 升级

1. 记录当前 Git 提交、容器镜像、配置版本，暂停写入并使用 `scripts/backup_restore.py` 备份 MySQL、Redis、Chroma 和原文件；另外安全保存备份密钥。按 [备份与恢复](cloud-recovery.md) 完成可恢复性检查。
2. 阅读目标版本 Release Notes，检查 `.env.example` 中新增配置。先在隔离环境用备份副本演练升级和恢复。
3. 执行 `docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d --build`。检查 Flyway 迁移成功、Java 和 Python 健康状态以及后台任务无持续失败。
4. 验证注册、登录、退出、上传和重解析、引用回答、记忆确认、密码重置、账号删除与备份恢复。破坏性演练使用隔离的 CI 栈，不能针对用户的主数据运行。

## 回退

先停止写入并保留日志。仅在确认旧应用与已迁移数据库兼容时回退镜像；不要自动逆转 Flyway 迁移或清空任务表。若迁移不兼容，在隔离环境验证备份后恢复整个一致性数据集和对应版本密钥，再切回旧版本。V14 会使旧的无会话 ID JWT 失效，升级后用户需重新登录。

验收命令见 [测试说明](testing.md)，本地部署命令见 [自部署指南](SELF_HOSTING.md)。

## Embedding 与恢复保护

升级后非空的旧向量集合如没有 profile 元数据，或模型/维度变化，会拒绝新增和检索；列表、导出、删除仍可用。不要手工补写 profile 伪装兼容。先备份、停止服务，按 [Embedding 迁移](EMBEDDING_MIGRATION.md) dry-run，再显式重建并核对报告；恢复使用匹配模型与快照。

`backup_restore.py restore ARCHIVE --yes` 先验证解密、空间、schema 上限及新归档记录的实际 MySQL Flyway 历史（迁移名称/版本/CRC32），再持久保存 `pre-restore-*.tar.gz`。导入/目录替换失败会恢复旧 SQL 和存储目录；回滚失败保持应用服务停止。通过 `--report` 指定状态报告位置，恢复包包含敏感数据，需按备份策略保护及清理。强杀/断电不具备自动原子恢复保证，启动前检查报告并手动恢复 recovery_archive。旧归档缺少 schema 元数据时只能在匹配版本隔离演练，格式版本校验不能代替数据库兼容性校验。
