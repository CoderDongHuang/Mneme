# 时间存储与显示

所有表示时刻的业务字段以 UTC 存储，界面依据每位用户保存的语言和 IANA 时区显示。个人资料可选择 English + Europe/Amsterdam 或简体中文 + Asia/Shanghai；刷新和重新登录后继续使用服务器保存的偏好。阿姆斯特丹的夏令时由浏览器 Intl 时区数据库处理，不使用固定小时偏移。

## 存储和兼容

- Java 的 JDBC 连接使用 `connectionTimeZone=UTC`、`forceConnectionTimeZoneToSession=true`，Hikari 建立每条连接时执行 `SET time_zone = '+00:00'`。自定义 JDBC URL 也必须保留 UTC 连接参数。
- MySQL `DATETIME` 不包含时区：默认 `CURRENT_TIMESTAMP` 在 UTC 会话中生成，Java 写入使用 UTC 或 `Instant`。Python MySQL 连接同样显式设置 UTC。
- Python 的持久化消息、会话、任务和记忆时间使用带 `+00:00` 的 ISO 8601；读取历史无偏移 SQL / ISO 时间时按 UTC 解释。过期、排序、记忆衰减和空闲蒸馏先解析成 UTC，不能按字符串或宿主时区比较。
- 前端共用 `utils/dates.js` 和 `useDateFormatter`。显式 `Z` / offset 表示实际时刻；历史无偏移值按 UTC 解释；空值和非法值显示 `—`。归档导入保留 offset 对应的时刻，不能截断到前 19 个字符。

## 日历日期

学习计划的 `target_date` 和服务端已经聚合的统计 `day` 是日历日期，使用语言格式化但不平移日期。复习卡 `due_at`、会话筛选和日历中的卡片归属则按用户时区计算。当前日统计仍使用服务端 UTC 聚合口径；切换时区不会伪造另一套当地日统计。

## 已有部署升级

默认 Docker 部署此前采用 UTC；本次不批量猜测或重写历史时间。曾自定义 JVM / MySQL 时区的部署，升级前应备份，核对连接会话时区以及一条已知时间的业务记录。若历史 `DATETIME` 实际按非 UTC 时区写入，必须先确认源时区，并在维护窗口转换为 UTC；夏令时回拨的重复本地时间需要额外记录判定，不能用固定偏移自动猜测。备份恢复后核验会话有效期、已知文档版本时间和到期卡片。

## 回归

单元测试覆盖跨午夜、显式偏移、无偏移历史值、阿姆斯特丹春秋夏令时、日历截止日及失效值。真实 MySQL 测试在不同 JVM 时区验证连接 UTC、归档时间、会话有效期。浏览器回归保存两套语言时区并刷新，检查会话、任务、文档版本、解析报告、计划、聊天日期筛选和运维时间；另使用实际 localhost 服务验证真实写入与显示。
