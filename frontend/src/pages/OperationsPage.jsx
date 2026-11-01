import { useFormatters } from '../hooks/useFormatters'
import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { useState } from 'react'
import { Activity, HardDrive, RefreshCw, Server, Timer } from 'lucide-react'
import { useOperationsData } from '../features/operations/useOperationsData'
import LoadingState from '../components/LoadingState'
import AdminAccess from '../components/AdminAccess'
import CleanupChecklist from '../components/CleanupChecklist'
import { FeedbackBlock, PageHeader, StatusPill } from '../components/ui'
import '../styles/centers.css'

function Table({ rows, columns }) {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  const [page, setPage] = useState(0)
  const lastPage = Math.max(0, Math.ceil((rows?.length || 0) / 10) - 1)
  const currentPage = Math.min(page, lastPage)
  if (!Array.isArray(rows)) return <p role="status">{t('数据不可用，请刷新运维状态重试。')}</p>
  return rows.length ? <>
    <div className="reference-table-wrap"><table className="reference-table"><thead><tr>{columns.map(([key, label]) => <th scope="col" key={key}>{t(label)}</th>)}</tr></thead><tbody>{rows.slice(currentPage * 10, (currentPage + 1) * 10).map((row, index) => <tr key={row.id || index}>{columns.map(([key]) => <td key={key}>{key === 'cleanup_report' ? <CleanupChecklist report={row[key]} /> : ['createdAt', 'next_attempt_at', 'completed_at'].includes(key) ? dates.dateTime(row[key]) : key === 'status' ? fmt.status(row[key]) : ['total', 'limit', 'attempt_count'].includes(key) ? fmt.integer(row[key]) : String(row[key] ?? '—')}</td>)}</tr>)}</tbody></table></div>
    {lastPage > 0 && <div className="operations-pagination"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t('上一页')}</button><span aria-live="polite">{t('第 {0} 页', [currentPage + 1])} / {lastPage + 1}</span><button disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>{t('下一页')}</button></div>}
  </> : <p className="account-empty">{t('暂无记录')}</p>
}
export default function OperationsPage() {
  useI18n()
  const [token, setToken] = useState('')
  if (token) return <OperationsContent key={token} token={token} onLock={() => setToken('')} />
  return <div className="standard-page account-page operations-page">
    <PageHeader title={t('管理员运维中心')} description={t('服务健康、运行指标与操作审计')} />
    <section className="account-card admin-unlock"><Server size={30} /><h2>{t('管理员访问验证')}</h2><p>{t('使用管理员凭证查看服务状态，凭证仅在当前页面临时使用。')}</p><AdminAccess onUnlock={setToken} /></section>
  </div>
}

function OperationsContent({ token, onLock }) {
  const fmt = useFormatters()
  useI18n()
  const dates = useDateFormatter()
  const { snapshot, audit, refresh } = useOperationsData(token)
  const data = snapshot.data
  const status = value => fmt.status(value, 'service')
  const monitoring = data?.monitoring || {}
  const health = data?.health || {}
  const services = [['MySQL', health.mysql], ['Redis', health.redis], ['Agent', health.agent?.status]]
  const ready = services.every(([, value]) => typeof value === 'string') ? services.filter(([, value]) => ['up', 'ready', 'ok', 'healthy'].includes(value)).length : '—'
  const tasksAvailable = data?.task_data_status === 'available'
  const capacity = data?.capacity || {}
  const disk = capacity.status === 'available' && capacity.disk_total_bytes > 0 ? (1 - capacity.disk_usable_bytes / capacity.disk_total_bytes) : null
  const metrics = [['mneme:gateway_availability:rate5m', '网关可用率'], ['mneme:gateway_latency_p95:rate5m', '网关 P95（秒）'], ['mneme:http_availability:rate5m', 'Agent 可用率'], ['mneme:http_latency_p95:rate5m', 'Agent P95（秒）']]
  const auditPanel = <section className="account-card" aria-labelledby="operations-audit-title" aria-busy={audit.loading}>
    <h2 id="operations-audit-title">{t('操作审计')}</h2><p className="muted">{t('最近 200 条操作记录；仅展示追踪与状态信息。')}</p>
    {audit.loading && <LoadingState label={t('正在读取审计记录')} />}
    <FeedbackBlock error={audit.error ? `${t('审计记录加载失败：')}${audit.error}` : ''} onRetry={audit.refresh} />
    {audit.error && audit.data !== null && <p>{t('已有审计记录可能不是最新状态。')}</p>}
    {audit.data !== null && <Table rows={audit.data} columns={[[ 'createdAt', '时间'], ['userId', '用户'], ['action', '操作'], ['resource', '资源'], ['statusCode', '状态码'], ['traceId', '追踪编号']]} />}
  </section>
  return <div className="standard-page account-page operations-page">
    <PageHeader title={t('管理员运维中心')} description={t('服务健康、运行指标与操作审计')}><button onClick={refresh} disabled={snapshot.loading || audit.loading}><RefreshCw size={16} />{t('刷新运维状态')}</button><button onClick={onLock}>{t('锁定')}</button></PageHeader>
    {snapshot.loading && <LoadingState label={t('正在读取运维状态')} />}
    <FeedbackBlock error={snapshot.error ? `${t('运维状态加载失败：')}${snapshot.error}` : ''} onRetry={snapshot.refresh} />
    {snapshot.error && data && <p role="status">{t('已有运维数据可能不是最新状态。')}</p>}
    {data && <>
      <p className="muted">{t('检查时间：')}{dates.dateTime(data.checked_at)}</p>
      <div className="operations-metrics">
        {[[Activity, '依赖就绪', `${ready} / ${services.length}`, '依赖健康'], [Server, '网关可用率', fmt.percent(monitoring['mneme:gateway_availability:rate5m'], 2), '最近 5 分钟'], [Timer, '网关 P95（秒）', fmt.decimal(monitoring['mneme:gateway_latency_p95:rate5m'], 3), '最近 5 分钟'], [HardDrive, '网关磁盘使用率', fmt.percent(disk), '网关本地磁盘']].map(([Icon, label, value, note]) => <div className="account-card" key={label}><span><Icon size={17} />{t(label)}</span><strong>{value}</strong><small>{t(note)}</small></div>)}
      </div>
      <div className="operations-grid">
        <section className="account-card"><h2>{t('依赖健康')}</h2><table className="service-health"><tbody>{services.map(([name, value]) => <tr key={name}><th scope="row">{name}</th><td><StatusPill tone={['up', 'ready', 'ok', 'healthy'].includes(value) ? 'success' : 'warning'}>{status(value)}</StatusPill></td></tr>)}</tbody></table><p className="muted">{t('以上为连接与依赖探针，不代表端到端功能通过。应另外验证上传、解析、检索、问答和引用。')}</p><details><summary>{t('依赖诊断详情')}</summary><pre>{JSON.stringify(health.agent?.components || {}, null, 2)}</pre></details></section>
        <section className="account-card"><h2>{t('SLO · 5 分钟窗口')}</h2><p>{status(monitoring.status)}</p><p className="muted">{t('目标可用率 99.5% · P95 ≤ 2 秒')}</p><dl className="operation-values">{metrics.map(([key, label]) => <div key={key}><dt>{t(label)}</dt><dd>{monitoring[key] == null ? t('暂无样本') : key.includes('availability') ? fmt.percent(monitoring[key], 2) : fmt.decimal(monitoring[key], 3)}</dd></div>)}</dl></section>
      </div>
    </>}
    {auditPanel}
    {data && <>
      <div className="operations-grid">
        <section className="account-card"><h2>{t('邮件服务')}</h2><p role="status">{t(({ configured: '邮件服务已配置', not_configured: '邮件服务未配置' })[data.mail?.status] || '数据不可用，请刷新运维状态重试。')}</p><p>{t('最近投递：')}{t(({ not_attempted: '尚未尝试', smtp_accepted: 'SMTP 已接收', failed: '投递失败' })[data.mail?.last_delivery?.status] || '未知')}</p><p className="muted">{t('配置状态与最近投递仅代表当前网关实例；SMTP 接收不保证邮件已到达收件箱。')}</p></section>
        <section className="account-card"><h2>{t('模型配置密钥')}</h2><p>{t('当前版本：')}{data.model_keys?.active_version || '—'}</p><p role="status">{t(({ current: '全部配置已使用当前密钥', required: '历史配置需要轮换', missing_keys: '缺少历史密钥，无法轮换', unavailable: '密钥状态不可用' })[data.model_keys?.rotation_status] || '密钥状态不可用')}</p>{data.model_keys?.development_jwt_fallback && <p>{t('开发模式正在使用 JWT 密钥回退')}</p>}<Table rows={data.model_keys?.stored_versions} columns={[[ 'key_version', '密钥版本'], ['total', '配置数量']]} /></section>
        <section className="account-card"><h2>{t('容量与限流')}</h2><p>{t('网关本地磁盘：')}{capacity.status === 'available' ? t('{0} 可用 / {1} 总量', [fmt.bytes(capacity.disk_usable_bytes), fmt.bytes(capacity.disk_total_bytes)]) : t('不可用')}</p><p>{t('对象存储就绪：')}{data.storage?.object_storage_ready == null ? '—' : data.storage.object_storage_ready ? t('是') : t('否')}</p><Table rows={data.rate_limits?.limits ? Object.entries(data.rate_limits.limits).map(([bucket, limit]) => ({ bucket, limit })) : undefined} columns={[[ 'bucket', '请求类型'], ['limit', '每 IP / 分钟限制']]} /></section>
        <section className="account-card"><h2>{t('任务队列')}</h2><p>{status(data.task_data_status)}</p><Table rows={tasksAvailable ? data.queue : undefined} columns={[[ 'task_type', '类型'], ['status', '状态'], ['total', '数量']]} /></section>
      </div>
      <section className="account-card"><h2>{t('告警')}</h2><Table rows={monitoring.status === 'available' && Array.isArray(monitoring.alerts) ? monitoring.alerts.map(a => ({ name: a.labels?.alertname, severity: a.labels?.severity, state: a.state, summary: a.annotations?.summary })) : undefined} columns={[[ 'name', '名称'], ['severity', '等级'], ['state', '状态'], ['summary', '摘要']]} /><Table rows={tasksAvailable ? data.task_alerts : undefined} columns={[[ 'task_id', '任务'], ['task_type', '类型'], ['status', '状态'], ['error_code', '错误代码'], ['attempt_count', '重试次数']]} /></section>
      <section className="account-card"><details><summary>{t('账号删除 Saga')}</summary><Table rows={tasksAvailable ? data.sagas : undefined} columns={[[ 'operation_id', '操作'], ['user_id', '用户'], ['status', '状态'], ['current_step', '当前步骤'], ['attempt_count', '次数'], ['next_attempt_at', '下次执行'], ['completed_at', '完成时间']]} /></details><details><summary>{t('文档与知识库删除')}</summary><Table rows={tasksAvailable ? data.deletion_tasks : undefined} columns={[[ 'task_id', '任务'], ['task_type', '类型'], ['status', '状态'], ['error_code', '错误代码'], ['attempt_count', '次数'], ['next_attempt_at', '下次执行'], ['cleanup_report', '清理核验']]} /></details></section>
    </>}
  </div>
}
