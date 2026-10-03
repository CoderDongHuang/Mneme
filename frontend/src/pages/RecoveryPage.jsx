import { RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import AdminAccess from '../components/AdminAccess'
import '../styles/centers.css'
export default function RecoveryPage() {
  const [token, setToken] = useState('')
  const [runs, setRuns] = useState([])
  const [evidence, setEvidence] = useState(null)
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  async function request(path = '', options = {}) {
    return api(`/admin/recovery${path}`, { ...options, headers: { 'X-Admin-Token': token } })
  }
  async function load() {
    try { setRuns((await request()).runs); setError('') } catch (e) { setError(e.message) }
  }
  useEffect(() => {
    if (!token) return
    let active = true
    const poll = async () => {
      try { const data = await api('/admin/recovery', { headers: { 'X-Admin-Token': token } }); if (active) { setRuns(data.runs); setError('') } }
      catch (e) { if (active) setError(e.message) }
    }
    poll(); const timer = setInterval(poll, 15000)
    return () => { active = false; clearInterval(timer) }
  }, [token])
  async function dispatch(e) {
    e.preventDefault(); setBusy(true); setNotice('')
    try { await request('', { method: 'POST', body: JSON.stringify({ confirmation }) }); setConfirmation(''); setNotice('已提交隔离演练，请等待 GitHub 分配运行编号'); await load() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="center-page">
    <header className="center-head"><h1>备份恢复管理</h1>{token && <button title="刷新历史" onClick={load}><RefreshCw size={18} /></button>}</header>
    <AdminAccess onUnlock={value => { setToken(value); setEvidence(null); setRuns([]) }} />
    {token && <button onClick={() => { setToken(''); setRuns([]); setEvidence(null) }}>锁定</button>}
    {error && <p className="page-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {token && <>
      <form onSubmit={dispatch}><fieldset><legend>隔离恢复演练</legend><p>演练仅使用 GitHub 临时环境和合成数据，不覆盖生产库。生产恢复必须经值班负责人审批。</p><label>确认语句<input placeholder="ISOLATED DRILL" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button disabled={busy || confirmation !== 'ISOLATED DRILL'}>发起演练</button></fieldset></form>
      <ul className="center-list">{runs.map(run => <li key={run.id}><div className="center-row"><strong>#{run.run_number} · {run.created_at}</strong><span>{run.conclusion || run.status}</span><button onClick={async () => { try { setEvidence(await request(`/${run.id}`)) } catch (e) { setError(e.message) } }}>校验与报告</button></div></li>)}</ul>
      {!runs.length && !error && <p>暂无演练历史</p>}
      {evidence && <section><h2>运行 #{evidence.run.run_number}</h2><a href={evidence.run.html_url} target="_blank" rel="noreferrer">GitHub 日志与报告下载</a>{evidence.jobs.map(job => <div key={job.id}><h3>{job.name}</h3><ol>{job.steps.map(s => <li key={s.number}>{s.name}: {s.conclusion || s.status}</li>)}</ol></div>)}<h3>报告附件</h3><ul>{evidence.artifacts.map(a => <li key={a.id}>{a.name} · {a.size_in_bytes} bytes · {a.expired ? '已过期' : '可下载'}</li>)}</ul></section>}
    </>}
  </div>
}
