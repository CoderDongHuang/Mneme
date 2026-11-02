import { useDateFormatter } from '../hooks/useDateFormatter'
import { useFormatters } from '../hooks/useFormatters'
import { t, useI18n } from '../i18n'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import SiteRecovery from './SiteRecovery'
import AdminAccess from './AdminAccess'
import LoadingState from './LoadingState'
import { FeedbackBlock, StatusPill } from './ui'
import { useRecoveryDrillData } from '../features/recovery/useRecoveryDrillData'
import '../styles/centers.css'

function UnlockedRecovery({ token, onLock }) {
  const dates = useDateFormatter()
  const fmt = useFormatters()
  const [confirmation, setConfirmation] = useState('')
  const { history, detail, submission, loadEvidence, dispatch } = useRecoveryDrillData(token)
  const evidence = detail.data
  async function submit(event) {
    event.preventDefault()
    if (await dispatch(confirmation)) setConfirmation('')
  }
  return <>
    <div className="center-toolbar"><button onClick={onLock}>{t('锁定')}</button><button aria-label={t('刷新历史')} onClick={history.refresh}><RefreshCw size={18} /></button></div>
    <SiteRecovery token={token} />
    <form onSubmit={submit}><fieldset disabled={submission.busy}><legend>{t('隔离恢复演练')}</legend><p>{t('演练仅使用 GitHub 临时环境和合成数据，不覆盖生产库。生产恢复必须经值班负责人审批。')}</p><label>{t('确认语句')}<input placeholder="ISOLATED DRILL" value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label><button disabled={submission.busy || confirmation !== 'ISOLATED DRILL'}>{submission.busy ? t('正在提交演练') : t('发起演练')}</button></fieldset></form>
    <FeedbackBlock error={submission.error} />
    <FeedbackBlock message={submission.notice} />
    <section aria-label={t('演练历史')} aria-busy={history.loading}>
      <h2>{t('演练历史')}</h2>
      {history.loading && <LoadingState label={t('正在读取演练历史')} />}
      <FeedbackBlock error={history.error ? t('演练历史加载失败：{0}', [history.error]) : ''} onRetry={history.refresh} />
      {history.data !== null && history.error && <p role="status">{t('已有演练历史可能不是最新状态。')}</p>}
      {history.data !== null && <ul className="center-list">{history.data.map(run => <li key={run.id}><div className="center-row"><strong>#{run.run_number} · {dates.dateTime(run.created_at)}</strong><StatusPill>{fmt.status(run.conclusion || run.status, 'recovery')}</StatusPill><button onClick={() => loadEvidence(run.id)}>{t('校验与报告')}</button></div></li>)}</ul>}
      {history.data?.length === 0 && !history.loading && !history.error && <p>{t('暂无演练历史')}</p>}
    </section>
    {detail.id !== null && <section aria-label={t('演练报告')} aria-busy={detail.loading}>
      {detail.loading && <LoadingState label={t('正在读取演练报告')} />}
      <FeedbackBlock error={detail.error ? t('演练报告加载失败：{0}', [detail.error]) : ''} onRetry={detail.refresh} />
      {evidence && <><h2>{t('运行 #')}{evidence.run.run_number}</h2><a href={evidence.run.html_url} target="_blank" rel="noreferrer">{t('GitHub 日志与报告下载')}</a>{evidence.jobs.map(job => <div key={job.id}><h3>{job.name}</h3><ol>{job.steps.map(step => <li key={step.number}>{step.name}: {fmt.status(step.conclusion || step.status, 'recovery')}</li>)}</ol></div>)}<h3>{t('报告附件')}</h3><ul>{evidence.artifacts.map(item => <li key={item.id}>{item.name} · {fmt.bytes(item.size_in_bytes)} · {item.expired ? t('已过期') : t('可下载')}</li>)}</ul></>}
    </section>}
  </>
}

export default function RecoveryDrill() {
  useI18n()
  const [access, setAccess] = useState(null)
  return <div className="center-page">
    <header className="center-head"><h1>{t('备份恢复管理')}</h1></header>
    {access ? <UnlockedRecovery key={access} token={access} onLock={() => setAccess(null)} /> : <AdminAccess onUnlock={setAccess} />}
  </div>
}
