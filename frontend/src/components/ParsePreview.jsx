import { useEffect, useState } from 'react'
import { endpoints } from '../api/client'
import '../styles/parse-preview.css'

export default function ParsePreview({ preview, initialPage }) {
  const report = preview.parse_report || {}
  const pages = report.pages || []
  const [pageNumber, setPageNumber] = useState(Number(initialPage) || pages[0]?.page || 1)
  const [tagText, setTagText] = useState('')
  const [notice, setNotice] = useState('')
  const id = preview.document.id
  useEffect(() => {
    let active = true
    endpoints.documentTags(id).then(tags => { if (active) setTagText(tags.join(', ')) }).catch(error => { if (active) setNotice(error.message) })
    return () => { active = false }
  }, [id])
  const page = pages.find(page => Number(page.page) === pageNumber) || pages[0]
  const hash = preview.document.sha256 || report.content_sha256
  const imageUrl = `/api/v1/workspace/documents/${id}/pages/${pageNumber}${hash ? `?sha256=${encodeURIComponent(hash)}` : ''}`
  return <section className="parse-preview">
    <form onSubmit={async event => {
      event.preventDefault()
      try { await endpoints.setDocumentTags(id, tagText.split(/[,，]/).map(tag => tag.trim()).filter(Boolean)); setNotice('标签已保存') }
      catch (error) { setNotice(error.message) }
    }}><label>资料标签<input aria-label="资料标签" value={tagText} onChange={event => setTagText(event.target.value)} placeholder="逗号分隔" /></label><button>保存标签</button></form>
    {notice && <p role="status">{notice}</p>}
    <details open={preview.extension !== 'pdf'}><summary>解析内容 · {report.page_count || pages.length} 页/段 · {report.chunk_count ?? preview.document.chunk_count} 个片段{preview.document.version_number ? ` · 版本 ${preview.document.version_number}` : ''}</summary>
      {report.preview_truncated && <p>预览达到体积上限，请下载原文件核对完整内容。</p>}
      {report.status === 'historical_report_unavailable' && <p>此历史版本未保留解析报告，原文件仍可查看。</p>}
      <label>页码 / 段落<select value={pageNumber} onChange={event => setPageNumber(Number(event.target.value))}>{pages.map(page => <option key={page.page} value={page.page}>{page.page}</option>)}</select></label>
      {preview.extension === 'pdf' && page?.ocr_regions?.length > 0 && <>
        <p>OCR 区域：浅色表示低于 70% 置信度，悬停查看识别文字与分值。</p>
        <div className="ocr-page"><img src={imageUrl} alt={`第 ${pageNumber} 页 OCR 区域预览`} />
          {page.ocr_regions.map((region, index) => {
            const [left, top, right, bottom] = region.region.split(',').map(Number)
            return <span key={index} title={`${region.text} · ${(region.confidence * 100).toFixed(1)}%`}
              style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%`, background: region.confidence < .7 ? 'rgba(164,106,49,.28)' : 'rgba(74,103,82,.08)' }} />
          })}
        </div>
      </>}
      {(page?.blocks || []).map((block, index) => <details key={index} open={block.type === 'table'}><summary>{block.type === 'table' ? '表格' : '抽取文本'} {block.section}</summary><pre>{block.content}</pre></details>)}
      {!page?.blocks?.length && <pre>{page?.text || '暂无逐页预览；重新解析可生成新版报告。'}</pre>}
      <details><summary>索引片段 {report.chunks_truncated ? '（前 500 个）' : ''}</summary>{(report.chunks || []).filter(chunk => Number(chunk.page) === pageNumber).map(chunk => <article key={chunk.index}><small>片段 {chunk.index + 1} · {chunk.type}</small><pre>{chunk.content}</pre></article>)}</details>
    </details>
  </section>
}
