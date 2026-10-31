# 数据库角色、初始化与升级

对应审查 P2-04 / MN-012。三个专用账号仅限 `mneme` schema：

| 账号 | 使用方 | 权限 |
|---|---|---|
| mneme_gateway | Java 业务连接池 | SELECT、INSERT、UPDATE、DELETE |
| mneme_agent | Python 辅助状态 | SELECT、INSERT、UPDATE、DELETE |
| mneme_migrator | Gateway 启动时的 Flyway 独立连接 | 上述 DML，加 CREATE、ALTER、DROP、INDEX、REFERENCES |

运行账号无 DDL、创建用户、授权或其他 schema 权限。DML 当前按整个业务 schema 授予，尚非逐表隔离。迁移账号可破坏本业务 schema，必须单独保管凭据，仅供受信任迁移使用。MySQL root 只交给运维管理、一次性配置 job 和备份恢复工具，不作为业务数据源。

## 首次启动

设置 `MYSQL_ROOT_PASSWORD`、`MYSQL_GATEWAY_PASSWORD`、`MYSQL_AGENT_PASSWORD`、`MYSQL_MIGRATION_PASSWORD`，生产使用四个独立随机值。基础/自托管允许三个业务密码缺失时回退 `SPRING_DATASOURCE_PASSWORD`，仅兼容旧本机配置；生产覆盖文件要求显式设置三个值。不要复用 root 密码。

`mysql-users` 在 MySQL 健康后执行管理脚本，成功后才启动应用。脚本也作用于已有数据卷，不依赖仅空卷执行的 docker-entrypoint-initdb.d。它创建或更新固定专用账号、重置这些账号原有授权，再授予表中权限，不删除业务数据。SQL 和密码不写入日志。

Python 不再自行建 MySQL 表：V13 已由 Flyway 管理四张辅助表。启动时只执行 SELECT，缺表最多等待 90 次（间隔 1 秒），鉴权/权限等其他错误立即失败。Gateway 在 Python 容器启动后即可启动并运行迁移，不等待 Python 健康，避免初始化循环。多实例同样由 Flyway 数据库锁协调迁移。

非 Docker 启动必须先由管理员执行该脚本或同等授权，再分别配置 Gateway 的 `SPRING_DATASOURCE_USERNAME/PASSWORD`、`SPRING_FLYWAY_USER/PASSWORD` 与 Python 的 `MYSQL_USER/PASSWORD`。先启动 Gateway 迁移，再启动 Python。不要给业务账号补 DDL 来绕过缺表错误。

## 已有卷升级与轮换

1. 进入维护窗口，创建并验证完整备份，记录旧镜像和密钥版本；停止所有 Gateway/Python 写入实例。
2. 配置三个新密码，执行 `docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm mysql-users`（自托管改用 selfhost 覆盖文件）。该操作会重置三个**专用**账号的授权和密码；确认没有其他应用共用这些账号。
3. 使用固定的新发布镜像重新创建 Gateway/Python；只 restart 不会更新环境变量。Flyway 使用迁移连接；业务连接使用 DML 账号。检查迁移、就绪和登录、上传、记忆、删除业务，再退出维护。
4. 验证两个业务账号可查询/写入业务数据，但 CREATE TABLE、DROP DATABASE、CREATE USER、其他 schema 的查询均被拒绝。不要在真实数据库尝试破坏性命令，使用隔离测试环境。

轮换同样需要停写、重跑 job、重新创建全部应用实例，避免旧连接池在密码更新期间重连失败。管理脚本须保留 LF 换行。外部托管数据库可由 DBA 执行同等授权，应用不需要 root。

## 备份、恢复与回滚

整站工具使用管理员连接导出/重建业务 schema，这是运维操作。归档不包含 MySQL 系统账号；恢复到新实例时必须先执行 `mysql-users` 重建账号，保留匹配的角色密钥，再启动应用。已有实例恢复业务 schema 不撤销 schema 级授权。账号 job 失败时禁止继续启动应用。

程序回滚须检查迁移兼容性，必要时恢复匹配的整站备份。旧版 Python 若尝试建表会被 DML 账号拒绝，不能通过重新授予 root 来掩盖不兼容；改用已验证兼容版本或在维护窗口恢复匹配版本。密钥通过独立渠道保管，不提交到 GitHub。
