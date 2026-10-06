import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import AdminAccess from '../components/AdminAccess'
import '../styles/centers.css'

function Table({ rows = [], columns }) {
  return rows.length ? <div className="center-table"><table><thead><tr>{columns.map(([key, label]) => <th scope="col" key={key}>{label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(([key]) => <td key={key}>{String(row[key] ?? '-')}</td>)}</tr>)}</tbody></table></div> : <p>暂无记录</p>
}
const statuses = { available: '可用', not_configured: '未配置监控数据源', unavailable: '数据源不可用', up: '正常', down: '异常' }
const status = v => statuses[v] || v
export default function OperationsPage() {
  const [token, setToken] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    if (!token) return
    let active = true
    async function load() { try { const result = await api('/admin/operations', { headers: { 'X-Admin-Token': token } }); if (active) { setData(result); setError('') } } catch (e) { if (active) { setData(null); setError(e.message) } } }
    load(); const timer = setInterval(load, 30000)
    return () => { active = false; clearInterval(timer) }
  }, [token, refresh])
  const monitoring = data?.monitoring
  const metrics = [['mneme:gateway_availability:rate5m', '网关可用率'], ['mneme:gateway_latency_p95:rate5m', '网关 P95（秒）'], ['mneme:http_availability:rate5m', 'Agent 可用率'], ['mneme:http_latency_p95:rate5m', 'Agent P95（秒）']]
  return <div className="center-page">
    <header className="center-head"><h1>管理员运维中心</h1>{token && <button title="刷新运维状态" onClick={() => setRefresh(v => v + 1)}><RefreshCw size={18} /></button>}</header>
    <AdminAccess onUnlock={v => { setToken(v); setData(null); setError('') }} />
    {token && <button onClick={() => { setToken(''); setData(null); setError('') }}>锁定</button>}
    {error && <p className="page-error" role="alert">{error}</p>}
    {token && data && <>
      <p>检查时间：{data.checked_at}</p>
      <section><h2>依赖健康</h2><dl><dt>MySQL</dt><dd>{status(data.health.mysql)}</dd><dt>Redis</dt><dd>{status(data.health.redis)}</dd><dt>Agent</dt><dd>{data.health.agent?.status || '未知'}</dd></dl><pre>{JSON.stringify(data.health.agent?.components || {}, null, 2)}</pre></section>
      <section><h2>SLO · 5 分钟窗口</h2><p>{status(monitoring.status)} · 目标可用率 99.5% · P95 ≤ 2 秒</p><dl>{metrics.map(([key, label]) => <div className="center-metric" key={key}><dt>{label}</dt><dd>{monitoring[key] == null ? '暂无样本' : Number(monitoring[key]).toFixed(4)}</dd></div>)}</dl></section>
      <section><h2>容量与限流</h2><p>网关本地磁盘：{data.capacity.status === 'available' ? `${(data.capacity.disk_usable_bytes / 2 ** 30).toFixed(2)} GiB 可用 / ${(data.capacity.disk_total_bytes / 2 ** 30).toFixed(2)} GiB 总量` : '不可用'}</p><p>对象存储就绪：{data.storage.object_storage_ready ? '是' : '否'}</p><Table rows={Object.entries(data.rate_limits.limits).map(([bucket, limit]) => ({ bucket, limit }))} columns={[['bucket', '请求类型'], ['limit', '每 IP / 分钟限制']]} /></section>
      <section><h2>告警</h2><Table rows={(monitoring.alerts || []).map(a => ({ name: a.labels?.alertname, severity: a.labels?.severity, state: a.state, summary: a.annotations?.summary }))} columns={[['name', '名称'], ['severity', '等级'], ['state', '状态'], ['summary', '摘要']]} /><Table rows={data.task_alerts} columns={[['task_id', '任务'], ['task_type', '类型'], ['status', '状态'], ['error_code', '错误代码'], ['attempt_count', '重试次数']]} /></section>
      <section><h2>任务队列</h2><p>{status(data.task_data_status)}</p><Table rows={data.queue} columns={[['task_type', '类型'], ['status', '状态'], ['total', '数量']]} /></section>
      <section><h2>账号删除 Saga</h2><Table rows={data.sagas} columns={[['operation_id', '操作'], ['user_id', '用户'], ['status', '状态'], ['current_step', '当前步骤'], ['attempt_count', '次数'], ['next_attempt_at', '下次执行'], ['completed_at', '完成时间']]} /></section>
      <section><h2>文档与知识库删除</h2><Table rows={data.deletion_tasks} columns={[['task_id', '任务'], ['task_type', '类型'], ['status', '状态'], ['error_code', '错误代码'], ['attempt_count', '次数'], ['next_attempt_at', '下次执行']]} /></section>
    </>}
  </div>
}
