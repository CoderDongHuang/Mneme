import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { useState } from 'react'
import { Activity, HardDrive, RefreshCw, Server, Timer } from 'lucide-react'
import { api } from '../api/client'
import { useSerialPoll } from '../hooks/useSerialPoll'
import AdminAccess from '../components/AdminAccess'
import { FeedbackBlock, PageHeader, StatusPill } from '../components/ui'
import '../styles/centers.css'

function Table({ rows = [], columns }) {
  const dates = useDateFormatter()
  const [page, setPage] = useState(0)
  const lastPage = Math.max(0, Math.ceil(rows.length / 10) - 1)
  const currentPage = Math.min(page, lastPage)
  return rows.length ? <>
    <div className="reference-table-wrap"><table className="reference-table"><thead><tr>{columns.map(([key, label]) => <th scope="col" key={key}>{t(label)}</th>)}</tr></thead><tbody>{rows.slice(currentPage * 10, (currentPage + 1) * 10).map((row, index) => <tr key={row.id || index}>{columns.map(([key]) => <td key={key}>{['createdAt', 'next_attempt_at', 'completed_at'].includes(key) ? dates.dateTime(row[key]) : String(row[key] ?? '—')}</td>)}</tr>)}</tbody></table></div>
    {lastPage > 0 && <div className="operations-pagination"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t('上一页')}</button><span aria-live="polite">{t('第 {0} 页', [currentPage + 1])} / {lastPage + 1}</span><button disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>{t('下一页')}</button></div>}
  </> : <p className="account-empty">{t('暂无记录')}</p>
}
const statuses = { available: '可用', not_configured: '未配置监控数据源', unavailable: '数据源不可用', up: '正常', ready: '正常', down: '异常', degraded: '异常' }
const status = v => t(statuses[v] || v || '未知')
export default function OperationsPage() {
  useI18n()
  const dates = useDateFormatter()
  const [token, setToken] = useState('')
  const [data, setData] = useState(null)
  const [audit, setAudit] = useState([])
  const [auditError, setAuditError] = useState('')
  const [error, setError] = useState('')
  const refresh = useSerialPoll(async ({ signal, current }) => {
    const options = { signal, headers: { 'X-Admin-Token': token } }
    const [snapshot, logs] = await Promise.allSettled([api('/admin/operations', options), api('/admin/audit', options)])
    if (!current()) return
    if (snapshot.status === 'fulfilled') { setData(snapshot.value); setError('') } else { setError(snapshot.reason.message) }
    if (logs.status === 'fulfilled') { setAudit(Array.isArray(logs.value) ? logs.value : []); setAuditError('') } else { setAuditError(logs.reason.message) }
  }, { enabled: !!token, scope: token, interval: 30000 })
  function clear(value = '') { setToken(value); setData(null); setAudit([]); setError(''); setAuditError('') }
  const monitoring = data?.monitoring || {}
  const health = data?.health || {}
  const services = [['MySQL', health.mysql], ['Redis', health.redis], ['Agent', health.agent?.status]]
  const ready = services.filter(([, value]) => ['up', 'ready', 'ok', 'healthy'].includes(value)).length
  const capacity = data?.capacity || {}
  const disk = capacity.status === 'available' && capacity.disk_total_bytes > 0 ? (1 - capacity.disk_usable_bytes / capacity.disk_total_bytes) * 100 : null
  const metrics = [['mneme:gateway_availability:rate5m', '网关可用率'], ['mneme:gateway_latency_p95:rate5m', '网关 P95（秒）'], ['mneme:http_availability:rate5m', 'Agent 可用率'], ['mneme:http_latency_p95:rate5m', 'Agent P95（秒）']]
  return <div className="standard-page account-page operations-page">
    <PageHeader title={t('管理员运维中心')} description={t('服务健康、运行指标与操作审计')}>{token && <><button onClick={refresh}><RefreshCw size={16} />{t('刷新运维状态')}</button><button onClick={() => clear()}>{t('锁定')}</button></>}</PageHeader>
    {!token && <section className="account-card admin-unlock"><Server size={30} /><h2>{t('管理员访问验证')}</h2><p>{t('使用管理员凭证查看服务状态，凭证仅在当前页面临时使用。')}</p><AdminAccess onUnlock={clear} /></section>}
    <FeedbackBlock error={error} onRetry={error && token ? refresh : undefined} />
    {token && !data && !error && <p role="status">{t('加载中...')}</p>}
    {token && data && <>
      <p className="muted">{t('检查时间：')}{dates.dateTime(data.checked_at)}</p>
      <div className="operations-metrics">
        {[[Activity, '依赖就绪', `${ready} / ${services.length}`, '依赖健康'], [Server, '网关可用率', monitoring['mneme:gateway_availability:rate5m'] == null ? '—' : `${(Number(monitoring['mneme:gateway_availability:rate5m']) * 100).toFixed(2)}%`, '最近 5 分钟'], [Timer, '网关 P95（秒）', monitoring['mneme:gateway_latency_p95:rate5m'] == null ? '—' : Number(monitoring['mneme:gateway_latency_p95:rate5m']).toFixed(3), '最近 5 分钟'], [HardDrive, '网关磁盘使用率', disk == null ? '—' : `${disk.toFixed(1)}%`, '网关本地磁盘']].map(([Icon, label, value, note]) => <div className="account-card" key={label}><span><Icon size={17} />{t(label)}</span><strong>{value}</strong><small>{t(note)}</small></div>)}
      </div>
      <div className="operations-grid">
        <section className="account-card"><h2>{t('依赖健康')}</h2><table className="service-health"><tbody>{services.map(([name, value]) => <tr key={name}><th scope="row">{name}</th><td><StatusPill tone={['up', 'ready', 'ok', 'healthy'].includes(value) ? 'success' : 'warning'}>{status(value)}</StatusPill></td></tr>)}</tbody></table><p className="muted">{t('以上为连接与依赖探针，不代表端到端功能通过。应另外验证上传、解析、检索、问答和引用。')}</p><details><summary>{t('依赖诊断详情')}</summary><pre>{JSON.stringify(health.agent?.components || {}, null, 2)}</pre></details></section>
        <section className="account-card"><h2>{t('SLO · 5 分钟窗口')}</h2><p>{status(monitoring.status)}</p><p className="muted">{t('目标可用率 99.5% · P95 ≤ 2 秒')}</p><dl className="operation-values">{metrics.map(([key, label]) => <div key={key}><dt>{t(label)}</dt><dd>{monitoring[key] == null ? t('暂无样本') : Number(monitoring[key]).toFixed(4)}</dd></div>)}</dl></section>
      </div>
      <section className="account-card"><h2>{t('操作审计')}</h2><p className="muted">{t('最近 200 条操作记录；仅展示追踪与状态信息。')}</p><FeedbackBlock error={auditError} onRetry={auditError ? refresh : undefined} /><Table rows={audit} columns={[[ 'createdAt', '时间'], ['userId', '用户'], ['action', '操作'], ['resource', '资源'], ['statusCode', '状态码'], ['traceId', '追踪编号']]} /></section>
      <div className="operations-grid">
        <section className="account-card"><h2>{t('邮件服务')}</h2><p role="status">{t(data.mail?.status === 'configured' ? '邮件服务已配置' : '邮件服务未配置')}</p><p>{t('最近投递：')}{t(({ not_attempted: '尚未尝试', smtp_accepted: 'SMTP 已接收', failed: '投递失败' })[data.mail?.last_delivery?.status] || '未知')}</p><p className="muted">{t('配置状态与最近投递仅代表当前网关实例；SMTP 接收不保证邮件已到达收件箱。')}</p></section>
        <section className="account-card"><h2>{t('模型配置密钥')}</h2><p>{t('当前版本：')}{data.model_keys?.active_version || '—'}</p><p role="status">{t(({ current: '全部配置已使用当前密钥', required: '历史配置需要轮换', missing_keys: '缺少历史密钥，无法轮换', unavailable: '密钥状态不可用' })[data.model_keys?.rotation_status] || '密钥状态不可用')}</p>{data.model_keys?.development_jwt_fallback && <p>{t('开发模式正在使用 JWT 密钥回退')}</p>}<Table rows={data.model_keys?.stored_versions} columns={[[ 'key_version', '密钥版本'], ['total', '配置数量']]} /></section>
        <section className="account-card"><h2>{t('容量与限流')}</h2><p>{t('网关本地磁盘：')}{capacity.status === 'available' ? t('{0} GiB 可用 / {1} GiB 总量', [(capacity.disk_usable_bytes / 2 ** 30).toFixed(2), (capacity.disk_total_bytes / 2 ** 30).toFixed(2)]) : t('不可用')}</p><p>{t('对象存储就绪：')}{data.storage?.object_storage_ready ? t('是') : t('否')}</p><Table rows={Object.entries(data.rate_limits?.limits || {}).map(([bucket, limit]) => ({ bucket, limit }))} columns={[[ 'bucket', '请求类型'], ['limit', '每 IP / 分钟限制']]} /></section>
        <section className="account-card"><h2>{t('任务队列')}</h2><p>{status(data.task_data_status)}</p><Table rows={data.queue} columns={[[ 'task_type', '类型'], ['status', '状态'], ['total', '数量']]} /></section>
      </div>
      <section className="account-card"><h2>{t('告警')}</h2><Table rows={(monitoring.alerts || []).map(a => ({ name: a.labels?.alertname, severity: a.labels?.severity, state: a.state, summary: a.annotations?.summary }))} columns={[[ 'name', '名称'], ['severity', '等级'], ['state', '状态'], ['summary', '摘要']]} /><Table rows={data.task_alerts} columns={[[ 'task_id', '任务'], ['task_type', '类型'], ['status', '状态'], ['error_code', '错误代码'], ['attempt_count', '重试次数']]} /></section>
      <section className="account-card"><details><summary>{t('账号删除 Saga')}</summary><Table rows={data.sagas} columns={[[ 'operation_id', '操作'], ['user_id', '用户'], ['status', '状态'], ['current_step', '当前步骤'], ['attempt_count', '次数'], ['next_attempt_at', '下次执行'], ['completed_at', '完成时间']]} /></details><details><summary>{t('文档与知识库删除')}</summary><Table rows={data.deletion_tasks} columns={[[ 'task_id', '任务'], ['task_type', '类型'], ['status', '状态'], ['error_code', '错误代码'], ['attempt_count', '次数'], ['next_attempt_at', '下次执行']]} /></details></section>
    </>}
  </div>
}
