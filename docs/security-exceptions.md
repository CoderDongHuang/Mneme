# Security exceptions

当前有三项有期例外：Chroma 的 `PYSEC-2026-3813`、`PYSEC-2026-3814`、`PYSEC-2026-3815`。最近复核 2026-10-28，到期 2026-11-10。影响范围和隔离措施以 [安全响应策略](SECURITY_RESPONSE_POLICY.md) 为准；例外不等于漏洞已修复。

Spring `CVE-2026-47884`、`CVE-2026-47890` 已通过 Spring Boot 4.0.9 / Spring Framework 7.0.10 升级处理，删除 `.trivyignore` 两项忽略和有期适用性检查，恢复普通依赖及镜像扫描，不再依赖“未使用视图”的例外判断。

前端 CI 使用 `audit-ci` 阻断 high/critical。新增例外必须先在安全响应策略记录公告编号、实际暴露面、补偿控制、负责人、到期日和移除条件，不能只修改 allowlist。
