import { t, useI18n } from '../i18n'

export default function DocumentIndexHealth({ document, busy, onRepair }) {
  useI18n()
  let report
  try { report = JSON.parse(document?.parseReport || '{}') } catch { return null }
  if (!report.vector_index_version) return null
  const repairing = document.status === 'index_repairing'
  const pending = repairing || report.vector_index_version !== report.lexical_index_version || report.index_status !== 'ready'
  return <section className="parse-report" aria-label={t('索引一致性')}>
    <strong role="status">{t(pending ? '向量索引可用，词法索引待修复' : '向量与词法索引版本一致')}</strong>
    <small>{t('向量版本：')}{report.vector_index_version.slice(0, 12)}</small>
    <small>{t('词法版本：')}{report.lexical_index_version?.slice(0, 12) || t('尚未完成')}</small>
    {pending && <><p>{t('仅重建词法索引，不重新解析文件或调用 Embedding。')}</p>
      {repairing ? <a href="/tasks">{t('修复任务已提交，查看任务中心')}</a> : onRepair && !['parsing', 'deleting', 'delete_failed'].includes(document.status) &&
        <button disabled={busy} onClick={() => onRepair(document)}>{t('修复词法索引')}</button>}
    </>}
  </section>
}
