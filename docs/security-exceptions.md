# Security exceptions

当前有三项 Chroma 依赖公告的有期隔离例外：`PYSEC-2026-3813`、`PYSEC-2026-3814`、`PYSEC-2026-3815`。影响范围、补偿控制、负责人和 2026-10-18 复核期限以 [安全响应策略](SECURITY_RESPONSE_POLICY.md) 为准。例外不等于漏洞已修复。

前端 CI 使用 `audit-ci` 阻断 high/critical。新增例外必须先在安全响应策略记录公告编号、实际暴露面、补偿控制、负责人、到期日和移除条件，不能只修改 allowlist。
