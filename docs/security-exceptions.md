# Security exceptions

当前有五项有期例外：Chroma 的 `PYSEC-2026-3813`、`PYSEC-2026-3814`、`PYSEC-2026-3815`，以及 Spring 的 `CVE-2026-47884`、`CVE-2026-47890`。最近复核 2026-10-27，到期 2026-11-10。影响范围、隔离措施和受影响 API 检查以 [安全响应策略](SECURITY_RESPONSE_POLICY.md) 为准；例外不等于漏洞已修复。

前端 CI 使用 `audit-ci` 阻断 high/critical。新增例外必须先在安全响应策略记录公告编号、实际暴露面、补偿控制、负责人、到期日和移除条件，不能只修改 allowlist。
