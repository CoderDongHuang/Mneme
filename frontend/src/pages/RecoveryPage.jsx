import { t, useI18n } from '../i18n'
import { useState } from 'react'
import { downloadWorkspaceArchive } from '../api/client'
import { useAuth } from '../state/AuthContext'
import { FeedbackBlock, PageHeader } from '../components/ui'
import RecoveryDrill from '../components/RecoveryDrill'
import PersonalRecovery from './PersonalRecovery'
import '../styles/centers.css'

export default function RecoveryPage() {
  useI18n();
  const { isAdmin } = useAuth()
  const [tab, setTab] = useState('restore')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <div className="standard-page"><PageHeader eyebrow={t("数据保护")} title={t("备份与恢复")} description={t("先校验，再预览影响范围，最后执行并验证。")} />
    <nav className="segmented-tabs" aria-label={t("备份恢复分组")}><button aria-pressed={tab === 'backup'} onClick={() => setTab('backup')}>{t("创建个人备份")}</button><button aria-pressed={tab === 'restore'} onClick={() => setTab('restore')}>{t("个人恢复向导")}</button>{isAdmin && <button aria-pressed={tab === 'admin'} onClick={() => setTab('admin')}>{t("管理员整站灾备")}</button>}</nav>
    <FeedbackBlock error={error} />
    {tab === 'backup' && <section className="settings-section"><h2>{t("保存当前个人工作区")}</h2><p>{t("导出关系数据和可用原始文件为 ZIP。归档未加密，请保存在受保护的位置；模型密钥和账户凭证不包含在个人导出中。")}</p><button className="primary-button" disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await downloadWorkspaceArchive() } catch (e) { setError(e.message) } finally { setBusy(false) } }}>{busy ? t("正在创建…") : t("下载个人归档")}</button><p>{t("下载后使用恢复向导校验清单与哈希，确认文件齐全。")}</p></section>}
    {tab === 'restore' && <PersonalRecovery />}
    {tab === 'admin' && isAdmin && <RecoveryDrill />}
  </div>
}
