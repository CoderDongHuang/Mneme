# 隐私策略与审计记录的独立读取

对应原审查 P3-03 的隐私页异常状态及 P2-14 的单一业务边界拆分；其他页面、后台清理保留策略和整个拆分计划仍需逐项核验。

## 页面行为

- 隐私策略和审计记录分别显示加载、读取失败与重试。首次读取失败不能显示“暂无记录”，只有成功返回空列表才能显示。
- 策略服务不可用时仍可使用独立的导出和 Trace 删除操作。
- 审计记录迁至 `features/privacy/PrivacyOperations.jsx`，重试不重新读取或覆盖策略草稿、删除确认输入。
- 刷新失败保留已有审计记录并提示可能过期；卸载或新一轮读取后忽略迟到响应。
- 保存策略或删除 Trace 以实际写入结果显示成功回执。后续审计读取失败单独提示，不能误报写入失败、重复执行删除或丢失成功回执。
- 写入失败保留草稿并允许再次提交；操作锁防止双击重复写入。写入期间禁用策略与确认输入。

## 验证

```powershell
cd frontend
npm test -- --maxWorkers=1
npm run lint
npm run build
$env:MNEME_REAL_E2E='true'
$env:MNEME_E2E_BASE_URL='http://127.0.0.1:3000'
npx playwright test e2e/privacy-states-real.spec.js --workers=1 --retries=0
```

真实用例需要运行中的 Gateway、Agent、MySQL 与 Docker 访问权限，纳入整栈 CI。只对策略/审计 GET 注入 503；注册、策略保存、成功重试读取、Trace 删除及账号清理均使用实际服务。创建两个隔离用户，在 Agent 实际配置的 SQLite 或 MySQL 中写入唯一测试 Trace，独立 SQL 验证本用户删除为零、另一个用户仍为一，并独立读取策略与审计记录验证持久化。仅明确的 429 可按有效 Retry-After 有限重试，500 不重试。

初轮本地夹具误把 Trace 写入未启用的 MySQL，而实际 Agent 使用 SQLite，导致读回断言失败。已清理四条隔离测试残留，修正夹具按实际后端写入、独立 SQL 读回后完整重跑。未改动生产删除逻辑或放松隔离断言。

最终桌面/移动两项通过，六张实际视口截图回查，无横向溢出；全量前端 25 文件 116 项、Lint、生产构建及原包大小门禁通过。独立读回 QA 用户与两种后端的测试 Trace 均为零、175 个账号删除任务全部 completed、Gateway/Agent 健康均 200。证据见 `artifacts/privacy-states-{unit-final,lint-final,build,real-accepted}.log` 与 `privacy-states-browser-accepted`（本地忽略目录）。

## 部署和回退

本项仅前端及回归入口，无数据库迁移，不改变 API。部署前保留原容器和匹配快照，以相同配置替换前端并确认健康；失败时恢复原前端容器和镜像，不需要回退数据库。用户数据清理、整站恢复及其他后端边界沿用各自流程，不由本页加载成功与否判定。
