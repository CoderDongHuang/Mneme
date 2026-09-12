# Security exceptions

当前没有允许忽略的 high 或 critical 依赖安全公告。

前端 CI 使用 `audit-ci` 阻断 high/critical。审计报告中的 moderate 仍需在常规依赖升级中处理；新增例外必须在本文记录公告编号、实际暴露面、补偿控制、负责人和移除条件，不能只修改 allowlist。
