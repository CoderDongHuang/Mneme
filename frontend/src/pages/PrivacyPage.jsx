import { useEffect, useState } from 'react'
import { Download, Save, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, endpoints, downloadWorkspaceArchive, downloadWorkspaceExport } from '../api/client'
import '../styles/centers.css'

export default function PrivacyPage() {
  const [policy, setPolicy] = useState(null)
  const [logs, setLogs] = useState([])
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    Promise.all([api('/privacy'), endpoints.operations()]).then(([p, l]) => { if (active) { setPolicy(p); setLogs(l) } }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])
  async function run(label, action) {
    setBusy(label); setError(''); setNotice('')
    try { await action(); setNotice(`${label}完成`); setLogs(await endpoints.operations()) }
    catch (e) { setError(e.message) } finally { setBusy('') }
  }
  return <div className="center-page">
    <header className="center-head"><h1>数据与隐私</h1><Link to="/profile">账号管理</Link></header>
    {error && <p role="alert" className="page-error">{error}</p>}
    <p role="status" aria-live="polite">{busy ? `${busy}处理中` : notice}</p>
    {policy && <>
      <section><h2>外部模型处理</h2><ul>{policy.providers.map(p => <li key={p}>{p}</li>)}</ul><h3>发送范围</h3><ul>{policy.sending_scope.map(s => <li key={s}>{s}</li>)}</ul>
        <form onSubmit={e => { e.preventDefault(); run('策略保存', async () => setPolicy(await api('/privacy', { method: 'PUT', body: JSON.stringify({ cloud_allowed: policy.cloud_allowed, trace_days: Number(policy.trace_days) }) }))) }}>
          <label><input type="checkbox" checked={policy.cloud_allowed} onChange={e => setPolicy({ ...policy, cloud_allowed: e.target.checked })} />允许外部模型处理</label>
          <label>Trace 保留天数<input type="number" min="1" max={policy.trace_max_days} required value={policy.trace_days} onChange={e => setPolicy({ ...policy, trace_days: e.target.value })} /></label>
          <button disabled={!!busy}><Save size={16} />保存策略</button>
        </form>
      </section>
      <section><h2>导出与删除</h2><div className="center-row"><button disabled={!!busy} onClick={() => run('JSON 导出', downloadWorkspaceExport)}><Download size={16} />导出数据</button><button disabled={!!busy} onClick={() => run('归档导出', downloadWorkspaceArchive)}><Download size={16} />导出含原文件归档</button></div>
        <form onSubmit={e => { e.preventDefault(); run('Trace 删除', async () => { await api(`/privacy/traces?confirmation=${encodeURIComponent(confirmation)}`, { method: 'DELETE' }); setConfirmation('') }) }}>
          <label>删除确认<input placeholder="DELETE TRACES" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button disabled={!!busy || confirmation !== 'DELETE TRACES'}><Trash2 size={16} />删除我的 Trace</button>
        </form>
      </section>
    </>}
    <section><h2>审计记录</h2><ul className="center-list">{logs.map((l, i) => <li key={`${l.operation_id}-${i}`}><strong>{l.operation_type}</strong> · {l.step} · {l.status}<time>{l.created_at}</time></li>)}</ul>{!logs.length && <p>暂无记录</p>}</section>
  </div>
}
