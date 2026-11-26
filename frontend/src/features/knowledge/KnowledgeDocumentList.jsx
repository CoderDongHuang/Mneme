import { useDateFormatter } from '../../hooks/useDateFormatter'
import { useFormatters } from '../../hooks/useFormatters'
import { t, useI18n } from '../../i18n'
import {
  ArrowUpRight,
  BookCopy,
  File,
  FileArchive,
  FileChartColumn,
  FileSpreadsheet,
  FileText,
  History,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { DangerZone } from '../../components/ui'
import StatusBadge from '../../components/StatusBadge'

const busyStatuses = ['deleting', 'parsing', 'index_repairing']

function ParseReport({ value }) {
  useI18n()
  const dates = useDateFormatter()
  let report
  try {
    report = JSON.parse(value)
    if (!report || typeof report !== 'object' || Array.isArray(report)
      || ['parser_version', 'indexed_at', 'content_sha256'].some(key => report[key] != null && typeof report[key] !== 'string')
      || (report.warnings != null && (!Array.isArray(report.warnings) || report.warnings.some(warning =>
        !warning || typeof warning !== 'object' || typeof warning.code !== 'string'
        || (warning.page != null && (!Number.isSafeInteger(warning.page) || warning.page < 0)))))) throw new Error('Invalid parse report')
  } catch {
    return <small>{t('解析报告格式无效，请重新解析')}</small>
  }
  const reasons = {
    no_text: t('未提取到文本（可能为空白页或扫描件）'),
    ocr_unavailable: t('OCR 不可用'),
    low_ocr_confidence: t('OCR 置信度偏低，请核对原文'),
    table_parser_unavailable: t('表格解析器不可用'),
    table_parse_failed: t('表格解析失败'),
    vision_parse_failed: t('图片理解失败'),
  }
  return <div className="parse-report">
    <small>{t('解析器：')}{report.parser_version || t('未知')}{t(' · 索引时间：')}{report.indexed_at ? dates.dateTime(report.indexed_at) : t('未知')}</small>
    <small>{t('文件 SHA-256：')}{report.content_sha256 || t('未知')}</small>
    {(report.warnings || []).map((warning, index) => <small key={index}>
      {warning.page > 0 ? t('第 {0} 页：', [warning.page]) : t('文件：')}{reasons[warning.code] || warning.code}
    </small>)}
    {!(report.warnings || []).length && <small>{t('已启用的解析步骤未报告异常；仍建议抽查原文。')}</small>}
  </div>
}

function fileIcon(name = '') {
  const extension = name.split('.').pop()?.toLowerCase()
  if (['xlsx', 'xlsm', 'csv'].includes(extension)) return FileSpreadsheet
  if (extension === 'pptx') return FileChartColumn
  if (extension === 'pdf') return FileArchive
  if (['md', 'markdown', 'txt', 'html', 'htm'].includes(extension)) return FileText
  return File
}

export default function KnowledgeDocumentList({
  documents,
  visibleDocuments,
  documentRead,
  documentsUnavailable,
  bulkBusy,
  selectedIds,
  setSelectedIds,
  previewDocument,
  documentBusy,
  onSelect,
  onShowVersions,
  onReplace,
  onReparse,
  onDelete,
  onBulk,
}) {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  useI18n()

  return <>
    <div className="document-table">
      <div className="document-row document-header"><span>{t('文件信息')}</span><span>{t('语义片段')}</span><span>{t('最后更新')}</span><span>{t('索引状态')}</span><span /></div>
      {visibleDocuments.map(document => {
        const Icon = fileIcon(document.fileName)
        const busy = busyStatuses.includes(document.status)
        return <div className={`document-row ${previewDocument?.id === document.id ? 'is-selected' : ''}`} key={document.id}>
          <div className="document-name"><input type="checkbox" aria-label={t('选择 {0}', [document.fileName])} disabled={documentsUnavailable || bulkBusy || busy} checked={selectedIds.includes(document.id)} onChange={event => setSelectedIds(ids => event.target.checked ? [...ids, document.id] : ids.filter(id => id !== document.id))} /><span className={`file-icon file-${document.fileName.split('.').at(-1).toLowerCase()}`}><Icon size={26} /><small>{document.fileName.split('.').at(-1).toUpperCase()}</small></span><div><button className="document-title" onClick={() => onSelect(document)}>{document.fileName}</button><small>{document.errorMessage || t('文档编号 {0}', [document.id])}</small></div></div>
          <span>{document.chunkCount || 0}</span><time>{document.updatedAt ? dates.date(document.updatedAt) : '—'}</time><StatusBadge status={document.status} />
          <details className="row-actions"><summary aria-label={t('文档操作：{0}', [document.fileName])}>···</summary><div>{!busy && <><button disabled={documentsUnavailable || documentBusy[document.id]} onClick={() => onShowVersions(document)}><History size={15} />{t('版本历史')}</button><button disabled={documentsUnavailable || documentBusy[document.id]} onClick={() => onReplace(document)}><RefreshCw size={15} />{t('替换文件')}</button><button disabled={documentsUnavailable || documentBusy[document.id]} onClick={() => onReparse(document)}><ArrowUpRight size={15} />{t('重新解析')}</button><button disabled={documentsUnavailable || documentBusy[document.id]} onClick={() => onDelete(document)}><Trash2 size={15} />{t('删除文档')}</button></>}{document.parseReport && <details><summary>{t('解析报告')}</summary><ParseReport value={document.parseReport} /></details>}</div></details>
        </div>
      })}
      {documentRead.data && !documentRead.error && !visibleDocuments.length && <div className="documents-empty"><BookCopy size={30} /><strong>{t(documents.length ? '没有符合筛选条件的资料' : '这里还没有资料')}</strong><span>{t(documents.length ? '请调整搜索或筛选条件。' : '可将文件拖入列表，或点击导入资料。')}</span></div>}
    </div>
    <details className="bulk-tools"><summary>{t('批量操作')} · {fmt.integer(selectedIds.length)} {t('已选择')}</summary><div className="action-row"><button disabled={documentsUnavailable || bulkBusy} onClick={() => setSelectedIds(visibleDocuments.filter(item => !busyStatuses.includes(item.status)).map(item => item.id))}>{t('选择筛选结果')}</button><button disabled={documentsUnavailable || bulkBusy || !selectedIds.length} onClick={() => onBulk('reparse')}>{t('重新解析所选 (')}{fmt.integer(selectedIds.length)})</button></div>{selectedIds.length > 0 && <DangerZone title={t('批量删除所选文档')} description={t('删除 {0} 个所选文档及其索引。失败项保留以便重试。', [fmt.integer(selectedIds.length)])} action={t('删除所选')} confirmText="DELETE DOCUMENTS" busy={documentsUnavailable || bulkBusy} onConfirm={() => onBulk('delete')} />}</details>
  </>
}
