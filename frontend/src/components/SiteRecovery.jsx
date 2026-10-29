import { t, useI18n } from '../i18n'
import { useState } from 'react'
import { api } from '../api/client'
import { useSerialPoll } from '../hooks/useSerialPoll'
import { DangerZone, FeedbackBlock, StatusPill } from './ui'

export default function SiteRecovery({ token }) {
  useI18n();
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState('')
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const request = (path = '', body) => api(`/admin/recovery/site${path}`, { headers: { 'X-Admin-Token': token }, ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) })
  const refresh = useSerialPoll(async ({ current }) => {
    try { const result = await request(); if (current()) { setData(result); setError('') } }
    catch (e) { if (current()) setError(e.message) }
  }, { enabled: !!token, scope: token, interval: 15000 })
  const running = busy || data?.jobs?.some(job => ['queued', 'running'].includes(job.status))
  async function submit(action) {
    const job = await request('/jobs', { action, confirmation: action === 'restore' ? 'RESTORE SITE' : 'BACKUP SITE', archive: selected, sha256: preview?.sha256 || '' })
    setNotice(t("已提交整站任务 {0}。恢复时网页会暂时断开，宿主机执行器继续运行。", [job.id]))
    await refresh()
  }
  return <section><h2>{t("整站备份与恢复")}</h2><p>{t("由 Docker 宿主机上的独立执行器运行真实备份脚本。停止应用写入后保存一致性快照；恢复前创建回滚检查点。执行日志和状态保留在宿主机，即使网关停止也可追踪。")}</p>
    <FeedbackBlock error={error} message={notice} onRetry={error ? refresh : undefined} />
    {data && <><DangerZone title={t("创建整站备份")} description={t("短暂停止应用服务以保持数据一致性。包含所有用户的关系数据、原文件和索引；加密状态由部署配置决定。")} action={t("创建整站备份")} confirmText="BACKUP SITE" onConfirm={() => submit('backup')} busy={running} />
      <label>{t("选择整站归档")}<select disabled={running} value={selected} onChange={e => { setSelected(e.target.value); setPreview(null); setNotice('') }}><option value="">{t("请选择")}</option>{data.archives.map(item => <option key={item.name} value={item.name}>{item.name} · {(item.bytes / 1024 / 1024).toFixed(1)} MB</option>)}</select></label>
      <button disabled={!selected || running} onClick={async () => { setBusy(true); setError(''); setPreview(null); try { setPreview(await request('/preview', { archive: selected })) } catch (e) { setError(e.message) } finally { setBusy(false) } }}>{t("验证完整性与兼容性")}</button>
      {preview && <section><h3>{t("整站恢复预览")}</h3><StatusPill tone="success">{t("清单、文件与数据库版本校验通过")}</StatusPill><dl className="definition-grid"><dt>{t("创建时间")}</dt><dd>{preview.created_at}</dd><dt>{t("加密 / 签名")}</dt><dd>{preview.security.encrypted ? t("已加密") : t("未加密")} / {preview.security.signed ? t("已签名") : t("未签名")}</dd><dt>{t("应用数据版本")}</dt><dd>{preview.metadata.application_schema_max ?? t("未提供")}</dd><dt>SHA-256</dt><dd className="break-word">{preview.sha256}</dd></dl><p>{t("覆盖：")}{preview.overwrites.join('、')}{t("。保留部署配置、密钥与备份归档。仅支持一致性的整站恢复，不能混合恢复部分数据库与旧索引。")}</p><p>{t("应用失败则恢复执行前快照；回滚失败时保持服务停止，避免继续写入。完成后需验证真实文档、登录与引用链路。")}</p><DangerZone title={t("覆盖当前整站数据")} description={t("恢复所选归档将替换所有用户的当前数据并暂停服务。请先通知使用者并确认维护窗口；保管加密密钥与回滚快照。")} action={t("执行整站恢复")} confirmText="RESTORE SITE" onConfirm={() => submit('restore')} busy={running} /></section>}
      <h3>{t("整站执行历史")}</h3><button onClick={refresh}>{t("刷新任务状态")}</button><ul className="record-list">{data.jobs.map(job => <li key={job.id}><div><strong>{job.action === 'restore' ? t("恢复") : t("备份")} · {job.created_at}</strong><p>{t("操作编号：")}{job.id}</p><StatusPill>{job.status}</StatusPill><p>{job.message}</p>{job.report && <dl><dt>{t("恢复阶段")}</dt><dd>{job.report.status}</dd><dt>{t("RTO / RPO（秒）")}</dt><dd>{job.report.rto_seconds ?? '—'} / {job.report.rpo_seconds ?? '—'}</dd></dl>}{job.checkpoint && <p>{t("回滚检查点：")}{job.checkpoint}</p>}</div></li>)}</ul>{!data.jobs.length && <p>{t("暂无整站操作记录。")}</p>}</>}
  </section>
}
