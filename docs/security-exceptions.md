# Security exceptions

当前无项目主动配置的漏洞扫描例外。Spring 的两项忽略已通过 Boot 4 / Spring 7 升级删除；Chroma 的三项 pip-audit 忽略已通过移除 Chroma 运行时并迁移 Qdrant 1.20.0 删除。详见[安全响应策略](SECURITY_RESPONSE_POLICY.md)。

CI 对 Python Linux/Windows 锁文件、Java 依赖、三种运行镜像、前端和密钥执行门禁。扫描无命中不代表零漏洞；Trivy 对尚无修复的镜像公告继续输出报告，现有 ignore-unfixed 策略未扩大。新增例外必须记录公告、影响、负责人、到期日及移除条件，不能仅改 allowlist。
