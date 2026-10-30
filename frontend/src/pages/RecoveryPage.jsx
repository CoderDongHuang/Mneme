import { t, useI18n } from '../i18n'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, Download, FileCheck2, ShieldCheck } from 'lucide-react'
import { downloadWorkspaceArchive } from '../api/client'
import { useAuth } from '../state/AuthContext'
import { FeedbackBlock, PageHeader, StatusPill } from '../components/ui'
import RecoveryDrill from '../components/RecoveryDrill'
import PersonalRecovery from './PersonalRecovery'
import '../styles/centers.css'

export default function RecoveryPage() {
  useI18n()
  const { isAdmin } = useAuth()
  const [tab, setTab] = useState('restore')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [downloads, setDownloads] = useState([])
  const lock = useRef(false)
  async function backup() {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const result = await downloadWorkspaceArchive()
      setDownloads(items => [{ at: new Date().toISOString(), bytes: result.bytes }, ...items])
    } catch (e) { setError(e.message) } finally { lock.current = false; setBusy(false) }
  }
  return <div className="standard-page account-page recovery-page">
    <PageHeader title={t('备份与恢复')} description={t('数据备份、恢复与导出管理')} />
    <FeedbackBlock error={error} />
    <div className="account-columns">
      <div className="recovery-main">
        <nav className="segmented-tabs" aria-label={t('备份恢复分组')}><button aria-pressed={tab === 'backup'} onClick={() => setTab('backup')}>{t('个人备份')}</button><button aria-pressed={tab === 'restore'} onClick={() => setTab('restore')}>{t('个人恢复向导')}</button>{isAdmin && <button aria-pressed={tab === 'admin'} onClick={() => setTab('admin')}>{t('管理员整站灾备')}</button>}</nav>
        {tab !== 'admin' && <section className="account-card recovery-overview"><ShieldCheck size={32} /><div><h2>{t('保护你的学习积累')}</h2><p>{t('先校验，再预览影响范围，最后执行并验证。')}</p><StatusPill>{t('个人归档 · 手动下载')}</StatusPill><p className="muted">{t('个人备份保存在你的设备上；整站备份与历史由管理员管理。')}</p></div></section>}
        {tab === 'backup' && <section className="account-card"><h2>{t('本次访问的导出记录')}</h2><p className="muted">{t('仅记录本页成功生成的下载，不代表文件已在设备上妥善保存。')}</p><div className="reference-table-wrap"><table className="reference-table"><thead><tr><th>{t('创建时间')}</th><th>{t('大小')}</th><th>{t('状态')}</th></tr></thead><tbody>{downloads.map(item => <tr key={item.at}><td>{new Date(item.at).toLocaleString()}</td><td>{(item.bytes / 1024 / 1024).toFixed(2)} MB</td><td><StatusPill tone="success">{t('下载已发起')}</StatusPill></td></tr>)}</tbody></table></div>{!downloads.length && <div className="account-empty"><Archive size={30} /><p>{t('本次访问尚未创建个人备份')}</p><button className="primary-button" disabled={busy} onClick={backup}>{t('创建个人备份')}</button></div>}</section>}
        <div hidden={tab !== 'restore'}><PersonalRecovery /></div>
        {tab === 'admin' && isAdmin && <RecoveryDrill />}
      </div>
      <aside className="account-aside">
        <section className="account-card"><Download size={23} /><h2>{t('手动备份')}</h2><p>{t('导出关系数据和可用原始文件为 ZIP。归档未加密，请保存在受保护的位置；模型密钥和账户凭证不包含在个人导出中。')}</p><button className="primary-button" disabled={busy} onClick={backup}>{busy ? t('正在创建…') : t('下载个人归档')}</button>{downloads.length > 0 && <p role="status">{t('下载已发起')}</p>}</section>
        <section className="account-card"><FileCheck2 size={23} /><h2>{t('恢复数据')}</h2><p>{t('下载后使用恢复向导校验清单与哈希，确认文件齐全。')}</p><button onClick={() => setTab('restore')}>{t('个人恢复向导')}</button></section>
        <section className="account-card"><h2>{t('数据与隐私')}</h2><p>{t('查看数据范围、导出记录或管理删除请求。')}</p><Link className="text-link" to="/privacy">{t('打开隐私中心 →')}</Link></section>
      </aside>
    </div>
  </div>
}
