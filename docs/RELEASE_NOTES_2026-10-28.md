# 2026-10-28 入库恢复、检索评测与 Spring 7 安全迁移

> 后续向量存储替换与例外移除见 [2026-10-29 验收](ACCEPTANCE_2026-10-29.md)；下文保留当时测量和限制。

进程强杀后的旧入库锁最长保留 12 小时、无答案检索评分恒真、逐改写重复云请求，会分别阻塞重试、掩盖无关召回和增加延迟。本批改为 owner 租约、实际空召回评分及批量查询，新增真实 Redis 故障验证与四组检索门禁。完整结果见 [实际验收](ACCEPTANCE_2026-10-28.md) 和 [路线图对照](ROADMAP_COVERAGE.md)。

## 升级

1. 停止新写入，等待活动任务退出，制作并核验加密备份，另存密钥。已有 12 小时旧锁不能在原进程运行时强删。
2. 重建 Python 镜像；安装必须使用对应平台锁文件。新增 jieba 0.42.1，上游仅发布 sdist，源码 SHA-256 已固定。无新增 Flyway 迁移，最高仍为 V20，前版迁移说明见 [2026-10-27 发布说明](RELEASE_NOTES_2026-10-27.md)。
3. `RETRIEVER_FOCUS_GATE_ENABLED=true` 默认开启，可独立关闭对比。过滤只覆盖部分中文具体名词表达，可能误拒答；不需重建现有向量索引。
4. schema 4/无答案评分 v2 与旧报告不可直接比较。周期检索基线使用 `target_domain_rag_v2.json`，仅覆盖检索；模型趋势须重新采集，不复用旧配置历史。
5. 按 [测试说明](testing.md) 执行真实 Redis、桌面/手机实际 URL、四组离线、真实模型抽样与已有删除/恢复门禁。云预算单独为 3000ms，原离线 250ms 不变；历史失败报告保留。

## 回滚与边界

停写并等待处理任务退出后切回已记录镜像，恢复匹配备份；不逆转 Flyway。租约不是 fencing，外部调用不能即时终止，跨存储不具备整体原子性。原有复杂 OCR、模型误判、生产云恢复及安全例外仍按验收和安全策略公开，不将小样本通过当作全部生产风险消除。

## 网关框架升级

Spring Boot 4.0.9 / Spring Framework 7.0.10 替换 Boot 3 / Spring 6，Java 最低版本仍为 17。配套升级 MyBatis Plus Boot 4 starter 与 springdoc，采用 Boot 4 的 RestClient、Flyway 和 OpenTelemetry 模块。现有 JSON 数据继续使用官方 Jackson 2 兼容模块，无新增数据库迁移或向量重建要求。

重建并启动 `java-gateway`：`docker compose build java-gateway`、`docker compose up -d --no-deps java-gateway`。自定义配置须将旧 `management.otlp.tracing.endpoint` 迁移至 `management.opentelemetry.tracing.export.otlp.endpoint`，`management.tracing.enabled` 迁移至 `management.tracing.export.enabled`；现有 `OTEL_EXPORTER_OTLP_ENDPOINT` 和 `OTEL_TRACING_ENABLED` 环境变量保持可用。回归注册登录、上传检索、SSE、来源版本、邮件及追踪后再放行写入。删除原 Spring 漏洞例外，Java 依赖和镜像扫描继续启用。

若升级失败，停写后恢复升级前记录的网关镜像与配置；旧网关存在已记录的 Spring 安全公告，仅可隔离诊断，不作为长期安全版本。其他数据服务无需为本次框架升级降级。

JWT 解析及注销显式复用 Jackson JSON 编解码器，修复首次并发鉴权时自动发现组件偶发抛出异常的问题。新增 64 并发回归，完整 Java 86 项及实际项目 URL 桌面/手机 8 项回归通过。
