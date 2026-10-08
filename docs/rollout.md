# 升级、验收与回退

本页适用于当前 Beta 自部署版本。历史 V3 迁移步骤已经过期；数据库以 `java-gateway/src/main/resources/db/migration` 中的 Flyway 迁移为准，当前最高版本为 V18。

## 升级

1. 记录当前 Git 提交、容器镜像、配置版本，暂停写入并使用 `scripts/backup_restore.py` 备份 MySQL、Redis、Chroma 和原文件；另外安全保存备份密钥。按 [备份与恢复](cloud-recovery.md) 完成可恢复性检查。
2. 阅读目标版本 Release Notes，检查 `.env.example` 中新增配置。先在隔离环境用备份副本演练升级和恢复。
3. 执行 `docker compose -f docker-compose.yml -f docker-compose.selfhost.yml up -d --build`。检查 Flyway 迁移成功、Java 和 Python 健康状态以及后台任务无持续失败。
4. 验证注册、登录、退出、上传和重解析、引用回答、记忆确认、密码重置、账号删除与备份恢复。破坏性演练使用隔离的 CI 栈，不能针对用户的主数据运行。

## 回退

先停止写入并保留日志。仅在确认旧应用与已迁移数据库兼容时回退镜像；不要自动逆转 Flyway 迁移或清空任务表。若迁移不兼容，在隔离环境验证备份后恢复整个一致性数据集和对应版本密钥，再切回旧版本。V14 会使旧的无会话 ID JWT 失效，升级后用户需重新登录。

验收命令见 [测试说明](testing.md)，本地部署命令见 [自部署指南](SELF_HOSTING.md)。
