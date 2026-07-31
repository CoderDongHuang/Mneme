# 公网生产部署

本文件只适用于需要让其他人通过互联网访问的场景。个人电脑或内网使用请直接参考 README 的 Docker 快速开始，不需要域名和 HTTPS。

## 必需配置

使用 `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` 前，必须配置：

- `PUBLIC_DOMAIN`：实际域名
- `PUBLIC_ORIGIN`、`CORS_ORIGINS`：只填写正式 HTTPS 来源
- `SECURE_COOKIES=true`
- 独立且随机的 `JWT_SECRET`、`INTERNAL_SERVICE_TOKEN`、`ADMIN_API_TOKEN`
- SMTP 主机、账号和密码，用于密码重置验证码
- DeepSeek 或 DashScope 模型 Key

## 数据与备份

单机生产仍使用本地卷，必须定期执行 `scripts/backup-data.ps1`，并将备份复制到异地对象存储或其他主机。每月至少在隔离环境执行一次 `scripts/restore-data.ps1` 恢复演练。多实例部署前，需要先替换为共享文件存储、托管 MySQL、Redis 和 Chroma 服务。

## 安全边界

当前内置上传校验包含大小、扩展名、文件头和可执行文件拦截。公网环境仍建议在网关或独立服务接入恶意文件扫描、WAF、监控告警和模型调用额度控制。

## 部署限制

当前默认架构是单机自部署，不提供多实例横向扩展、自动故障转移或生产级 SLA。上线前请自行完成压力测试、备份恢复验证、日志留存和隐私/服务条款准备。
