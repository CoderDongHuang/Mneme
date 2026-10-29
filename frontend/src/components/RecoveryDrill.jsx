import { t, useI18n } from '../i18n'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import SiteRecovery from './SiteRecovery'
import { useSerialPoll } from '../hooks/useSerialPoll'
import AdminAccess from './AdminAccess'
import '../styles/centers.css'
export default function RecoveryDrill() {
  useI18n();
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
  useSerialPoll(async ({ current, signal }) => {
    try { const data = await api('/admin/recovery', { signal, headers: { 'X-Admin-Token': token } }); if (current()) { setRuns(data.runs); setError('') } }
    catch (e) { if (current()) setError(e.message) }
  }, { enabled: !!token, scope: token, interval: 15000 })
  async function dispatch(e) {
    e.preventDefault(); setBusy(true); setNotice('')
    try { await request('', { method: 'POST', body: JSON.stringify({ confirmation }) }); setConfirmation(''); setNotice(t("已提交隔离演练，请等待 GitHub 分配运行编号")); await load() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="center-page">
    <header className="center-head"><h1>{t("备份恢复管理")}</h1>{token && <button title={t("刷新历史")} onClick={load}><RefreshCw size={18} /></button>}</header>
    <AdminAccess onUnlock={value => { setToken(value); setEvidence(null); setRuns([]) }} />
    {token && <button onClick={() => { setToken(''); setRuns([]); setEvidence(null) }}>{t("锁定")}</button>}
    {error && <p className="page-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {token && <SiteRecovery key={token} token={token} />}
    {token && <>
      <form onSubmit={dispatch}><fieldset><legend>{t("隔离恢复演练")}</legend><p>{t("演练仅使用 GitHub 临时环境和合成数据，不覆盖生产库。生产恢复必须经值班负责人审批。")}</p><label>{t("确认语句")}<input placeholder="ISOLATED DRILL" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button disabled={busy || confirmation !== 'ISOLATED DRILL'}>{t("发起演练")}</button></fieldset></form>
      <ul className="center-list">{runs.map(run => <li key={run.id}><div className="center-row"><strong>#{run.run_number} · {run.created_at}</strong><span>{run.conclusion || run.status}</span><button onClick={async () => { try { setEvidence(await request(`/${run.id}`)) } catch (e) { setError(e.message) } }}>{t("校验与报告")}</button></div></li>)}</ul>
      {!runs.length && !error && <p>{t("暂无演练历史")}</p>}
      {evidence && <section><h2>{t("运行 #")}{evidence.run.run_number}</h2><a href={evidence.run.html_url} target="_blank" rel="noreferrer">{t("GitHub 日志与报告下载")}</a>{evidence.jobs.map(job => <div key={job.id}><h3>{job.name}</h3><ol>{job.steps.map(s => <li key={s.number}>{s.name}: {s.conclusion || s.status}</li>)}</ol></div>)}<h3>{t("报告附件")}</h3><ul>{evidence.artifacts.map(a => <li key={a.id}>{a.name} · {a.size_in_bytes} bytes · {a.expired ? t("已过期") : t("可下载")}</li>)}</ul></section>}
    </>}
  </div>
}
