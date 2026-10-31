import { useFormatters } from '../hooks/useFormatters'
import { t } from '../i18n'

const labels = { qdrant_chunks: '向量片段', qdrant_collections: '向量集合', fts_rows: '词法索引行', files: '文件与缓存', object_prefix: '对象存储前缀', mysql_rows: '数据库记录' }
export default function CleanupChecklist({ report }) {
  const fmt = useFormatters()
  if (!report) return <span>{t('尚未核验')}</span>
  let parsed
  try { parsed = typeof report === 'string' ? JSON.parse(report) : report } catch { return <span>{t('核验清单不可用')}</span> }
  if (!parsed?.counts || typeof parsed.counts !== 'object' || Array.isArray(parsed.counts)) return <span>{t('核验清单不可用')}</span>
  const verified = parsed.status === 'verified' && Object.keys(parsed.counts).length > 0 && Object.values(parsed.counts).every(count => count === 0)
  return <details><summary>{t(verified ? '清理已核验' : '清理待核验')}</summary>
    <dl>{Object.entries(parsed.counts).map(([key, count]) => <div key={key}><dt>{t(labels[key] || key)}</dt><dd>{Number.isSafeInteger(count) && count >= 0 ? fmt.integer(count) : t('未知（读取失败）')}</dd></div>)}</dl>
    <small>{t('仅核验在线数据的逻辑删除；备份与磁盘物理擦除适用独立策略。')}</small>
  </details>
}
