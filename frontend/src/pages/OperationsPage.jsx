import { t, useI18n } from '../i18n'
import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useSerialPoll } from '../hooks/useSerialPoll'
import AdminAccess from '../components/AdminAccess'
import '../styles/centers.css'

function Table({ rows = [], columns }) {
  useI18n();
  return rows.length ? <div className="center-table"><table><thead><tr>{columns.map(([key, label]) => <th scope="col" key={key}>{t(label)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(([key]) => <td key={key}>{String(row[key] ?? '-')}</td>)}</tr>)}</tbody></table></div> : <p>{t("暂无记录")}</p>
}
const statuses = { available: '可用', not_configured: '未配置监控数据源', unavailable: '数据源不可用', up: '正常', down: '异常' }
const status = v => statuses[v] || v
export default function OperationsPage() {
  useI18n();
  const [token, setToken] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const refresh = useSerialPoll(async ({ signal, current }) => {
    try { const result = await api('/admin/operations', { signal, headers: { 'X-Admin-Token': token } }); if (current()) { setData(result); setError('') } }
    catch (e) { if (current()) setError(e.message) }
  }, { enabled: !!token, scope: token, interval: 30000 })
  const monitoring = data?.monitoring
  const metrics = [['mneme:gateway_availability:rate5m', t("网关可用率")], ['mneme:gateway_latency_p95:rate5m', t("网关 P95（秒）")], ['mneme:http_availability:rate5m', t("Agent 可用率")], ['mneme:http_latency_p95:rate5m', t("Agent P95（秒）")]]
  return <div className="center-page">
    <header className="center-head"><h1>{t("管理员运维中心")}</h1>{token && <button title={t("刷新运维状态")} onClick={refresh}><RefreshCw size={18} /></button>}</header>
    <AdminAccess onUnlock={v => { setToken(v); setData(null); setError('') }} />
    {token && <button onClick={() => { setToken(''); setData(null); setError('') }}>{t("锁定")}</button>}
    {error && <p className="page-error" role="alert">{error}</p>}
    {token && data && <>
      <p>{t("检查时间：")}{data.checked_at}</p>
      <section><h2>{t("依赖健康")}</h2><dl><dt>MySQL</dt><dd>{status(data.health.mysql)}</dd><dt>Redis</dt><dd>{status(data.health.redis)}</dd><dt>Agent</dt><dd>{data.health.agent?.status || t("未知")}</dd></dl><p>{t("以上为连接与依赖探针，不代表端到端功能通过。应另外验证上传、解析、检索、问答和引用。")}</p><details><summary>{t("依赖诊断详情")}</summary><pre>{JSON.stringify(data.health.agent?.components || {}, null, 2)}</pre></details></section>
      <section><h2>{t("SLO · 5 分钟窗口")}</h2><p>{status(monitoring.status)}{t(" · 目标可用率 99.5% · P95 ≤ 2 秒")}</p><dl>{metrics.map(([key, label]) => <div className="center-metric" key={key}><dt>{t(label)}</dt><dd>{monitoring[key] == null ? t("暂无样本") : Number(monitoring[key]).toFixed(4)}</dd></div>)}</dl></section>
      <section><h2>{t("容量与限流")}</h2><p>{t("网关本地磁盘：")}{data.capacity.status === 'available' ? t("{0} GiB 可用 / {1} GiB 总量", [(data.capacity.disk_usable_bytes / 2 ** 30).toFixed(2), (data.capacity.disk_total_bytes / 2 ** 30).toFixed(2)]) : t("不可用")}</p><p>{t("对象存储就绪：")}{data.storage.object_storage_ready ? t("是") : t("否")}</p><Table rows={Object.entries(data.rate_limits.limits).map(([bucket, limit]) => ({ bucket, limit }))} columns={[['bucket', t("请求类型")], ['limit', t("每 IP / 分钟限制")]]} /></section>
      <section><h2>{t("告警")}</h2><Table rows={(monitoring.alerts || []).map(a => ({ name: a.labels?.alertname, severity: a.labels?.severity, state: a.state, summary: a.annotations?.summary }))} columns={[['name', t("名称")], ['severity', t("等级")], ['state', t("状态")], ['summary', t("摘要")]]} /><Table rows={data.task_alerts} columns={[['task_id', t("任务")], ['task_type', t("类型")], ['status', t("状态")], ['error_code', t("错误代码")], ['attempt_count', t("重试次数")]]} /></section>
      <section><h2>{t("任务队列")}</h2><p>{status(data.task_data_status)}</p><Table rows={data.queue} columns={[['task_type', t("类型")], ['status', t("状态")], ['total', t("数量")]]} /></section>
      <section><h2>{t("账号删除 Saga")}</h2><Table rows={data.sagas} columns={[['operation_id', t("操作")], ['user_id', t("用户")], ['status', t("状态")], ['current_step', t("当前步骤")], ['attempt_count', t("次数")], ['next_attempt_at', t("下次执行")], ['completed_at', t("完成时间")]]} /></section>
      <section><h2>{t("文档与知识库删除")}</h2><Table rows={data.deletion_tasks} columns={[['task_id', t("任务")], ['task_type', t("类型")], ['status', t("状态")], ['error_code', t("错误代码")], ['attempt_count', t("次数")], ['next_attempt_at', t("下次执行")]]} /></section>
    </>}
  </div>
}
