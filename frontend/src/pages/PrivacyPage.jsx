import { t, useI18n } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { Download, Save, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, endpoints, downloadWorkspaceArchive, downloadWorkspaceExport } from '../api/client'
import { DangerZone, FeedbackBlock, PageHeader } from '../components/ui'
import LoadingState from '../components/LoadingState'
import PrivacyOperations from '../features/privacy/PrivacyOperations'
import { useAuth } from '../state/AuthContext'
import '../styles/centers.css'
import '../styles/reference-pages.css'

export default function PrivacyPage() {
  useI18n();
  const { logout } = useAuth()
  const lock = useRef(false)
  const [policy, setPolicy] = useState(null)
  const [policyRead, setPolicyRead] = useState({ loading: true, error: '' })
  const [policyAttempt, setPolicyAttempt] = useState(0)
  const [logRevision, setLogRevision] = useState(0)
  const alive = useRef(false)
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    let active = true
    setPolicyRead({ loading: true, error: '' })
    api('/privacy').then(value => {
      if (active) { setPolicy(value); setPolicyRead({ loading: false, error: '' }) }
    }).catch(error => { if (active) setPolicyRead({ loading: false, error: error.message }) })
    return () => { active = false }
  }, [policyAttempt])
  async function run(label, action) {
    if (lock.current) return
    lock.current = true
    setBusy(label); setError(''); setNotice('')
    try {
      const result = await action()
      if (alive.current) { setNotice(t("{0}完成", [label])); setLogRevision(value => value + 1) }
      return result
    } catch (e) { if (alive.current) setError(e.message); throw e }
    finally { lock.current = false; if (alive.current) setBusy('') }
  }
  function act(label, action) { void run(label, action).catch(() => {}) }
  return <div className="center-page reference-page reference-privacy">
    <PageHeader title={t("数据与隐私")} description={t("了解数据去向，并管理导出、保留和删除。")}><Link to="/profile">{t("账号管理")}</Link></PageHeader>
    <section><h2>{t("数据如何流转")}</h2><ol className="data-flow"><li>{t("资料、会话、偏好保存在部署方数据库与文件存储中。")}</li><li>{t("检索会提取相关片段；启用外部模型时，将问题、必要上下文和选中的记忆发送给当前模型供应商。")}</li><li>{t("文档向量化、图片理解与后台任务使用部署方配置的服务，可能涉及外部供应商。个人模型配置用于当前用户的交互请求，不替代后台服务。")}</li><li>{t("个人密钥在服务端加密保存，页面不回传明文；备份密文需要相同的服务器加密密钥才能恢复。")}</li></ol><Link to="/settings">{t("检查模型服务")}</Link> · <Link to="/recovery">{t("恢复个人数据")}</Link></section>
    <FeedbackBlock error={error} />
    <p role="status" aria-live="polite">{busy ? t("{0}处理中", [busy]) : notice}</p>
    {policyRead.loading && <LoadingState label={t('正在读取隐私策略')} />}
    <FeedbackBlock error={policyRead.error ? `${t('隐私策略加载失败：')}${policyRead.error}` : ''} onRetry={() => setPolicyAttempt(value => value + 1)} />
    {policy &&
      <section><h2>{t("外部模型处理")}</h2><ul>{policy.providers.map(p => <li key={p}>{p}</li>)}</ul><h3>{t("发送范围")}</h3><ul>{policy.sending_scope.map(s => <li key={s}>{s}</li>)}</ul>
        <form onSubmit={e => { e.preventDefault(); act(t("策略保存"), async () => {
          const saved = await api('/privacy', { method: 'PUT', body: JSON.stringify({ cloud_allowed: policy.cloud_allowed, trace_days: Number(policy.trace_days) }) })
          if (alive.current) setPolicy(saved)
        }) }}>
          <label><input type="checkbox" disabled={!!busy} checked={policy.cloud_allowed} onChange={e => setPolicy({ ...policy, cloud_allowed: e.target.checked })} />{t("允许外部模型处理")}</label>
          <label>{t("Trace 保留天数")}<input type="number" disabled={!!busy} min="1" max={policy.trace_max_days} required value={policy.trace_days} onChange={e => setPolicy({ ...policy, trace_days: e.target.value })} /></label>
          <button disabled={!!busy}><Save size={16} />{t("保存策略")}</button>
        </form>
      </section>}
      <section><h2>{t("导出与删除")}</h2><div className="center-row"><button disabled={!!busy} onClick={() => act(t("JSON 导出"), downloadWorkspaceExport)}><Download size={16} />{t("导出数据")}</button><button disabled={!!busy} onClick={() => act(t("归档导出"), downloadWorkspaceArchive)}><Download size={16} />{t("导出含原文件归档")}</button></div>
        <form onSubmit={e => { e.preventDefault(); act(t("Trace 删除"), async () => { await api(`/privacy/traces?confirmation=${encodeURIComponent(confirmation)}`, { method: 'DELETE' }); if (alive.current) setConfirmation('') }) }}>
          <label>{t("删除确认")}<input disabled={!!busy} placeholder="DELETE TRACES" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button disabled={!!busy || confirmation !== 'DELETE TRACES'}><Trash2 size={16} />{t("删除我的 Trace")}</button>
        </form>
      </section>
    <DangerZone title={t("删除账号及全部关联数据")} description={t("提交不可撤销的账号删除任务：包括会话、学习记录、模型配置、原始文件、向量索引与记忆。确认后立即退出，后台任务继续清理；管理员可在运维中心追踪操作编号。请先导出需要保留的资料。")} action={t("删除我的账号")} confirmText="DELETE MY ACCOUNT" busy={!!busy} onConfirm={async () => { const result = await endpoints.deleteAccount(); window.alert(t("删除任务已提交，操作编号：{0}", [result.operation_id])); logout() }} />
    <PrivacyOperations revision={logRevision} />
  </div>
}
