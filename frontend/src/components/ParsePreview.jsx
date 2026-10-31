import { t, useI18n } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'
import '../styles/parse-preview.css'

export default function ParsePreview({ preview, initialPage }) {
  return <DocumentPreview key={preview.document.id} preview={preview} initialPage={initialPage} />
}

function DocumentPreview({ preview, initialPage }) {
  useI18n();
  const report = preview.parse_report || {}
  const pages = report.pages || []
  const [pageNumber, setPageNumber] = useState(Number(initialPage) || pages[0]?.page || 1)
  const [tagText, setTagText] = useState('')
  const [notice, setNotice] = useState('')
  const [overlay, setOverlay] = useState(true)
  const [saving, setSaving] = useState(false)
  const tagsEdited = useRef(false)
  const id = preview.document.id
  useEffect(() => {
    let active = true
    endpoints.documentTags(id).then(tags => { if (active && !tagsEdited.current) setTagText(tags.join(', ')) }).catch(error => { if (active && !tagsEdited.current) setNotice(error.message) })
    return () => { active = false }
  }, [id])
  const page = pages.find(page => Number(page.page) === pageNumber) || pages[0]
  const hash = preview.document.sha256 || report.content_sha256
  const imageUrl = `/api/v1/workspace/documents/${id}/pages/${pageNumber}${hash ? `?sha256=${encodeURIComponent(hash)}` : ''}`
  return <section className="parse-preview">
    <form onSubmit={async event => {
      event.preventDefault()
      if (saving) return
      setSaving(true)
      try { await endpoints.setDocumentTags(id, tagText.split(/[,，]/).map(tag => tag.trim()).filter(Boolean)); setNotice(t("标签已保存")) }
      catch (error) { setNotice(error.message) }
      finally { setSaving(false) }
    }}><label>{t("资料标签")}<input aria-label={t("资料标签")} value={tagText} onChange={event => { tagsEdited.current = true; setTagText(event.target.value) }} placeholder={t("逗号分隔")} /></label><button disabled={saving}>{t("保存标签")}</button></form>
    {notice && <p role="status">{notice}</p>}
    <details open={preview.extension !== 'pdf'}><summary>{t("解析内容 · ")}{report.page_count || pages.length}{t(" 页/段 · ")}{report.chunk_count ?? preview.document.chunk_count}{t(" 个片段")}{preview.document.version_number ? t(" · 版本 {0}", [preview.document.version_number]) : ''}</summary>
      {report.preview_truncated && <p>{t("预览达到体积上限，请下载原文件核对完整内容。")}</p>}
      {report.status === 'historical_report_unavailable' && <p>{t("此历史版本未保留解析报告，原文件仍可查看。")}</p>}
      <label>{t("页码 / 段落")}<select value={pageNumber} onChange={event => setPageNumber(Number(event.target.value))}>{pages.map(page => <option key={page.page} value={page.page}>{page.page}</option>)}</select></label>
      {preview.extension === 'pdf' && page?.ocr_regions?.length > 0 && <>
        <label><input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} />{t("显示 OCR 区域")}</label><p>{t("图例：琥珀区域表示低于 70% 的系统估计置信度，青绿区域表示其他识别区域。置信度不代表正确性保证。")}</p>
        <div className="action-row" aria-label={t("低置信度页面")}>{pages.filter(item => item.ocr_regions?.some(region => region.confidence < .7)).map(item => <button key={item.page} onClick={() => setPageNumber(Number(item.page))}>{t("核对第 ")}{item.page}{t(" 页")}</button>)}</div>
        <div className="ocr-page"><img src={imageUrl} alt={t("第 {0} 页 OCR 区域预览", [pageNumber])} />
          {overlay && page.ocr_regions.map((region, index) => {
            const [left, top, right, bottom] = region.region.split(',').map(Number)
            return <span key={index} title={`${region.text} · ${(region.confidence * 100).toFixed(1)}%`}
              className={region.confidence < .7 ? 'ocr-low' : 'ocr-normal'} tabIndex={0} aria-label={`${region.text} · ${(region.confidence * 100).toFixed(1)}%`}
              style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` }} />
          })}
        </div>
      </>}
      {(page?.blocks || []).map((block, index) => <details key={index} open={block.type === 'table'}><summary>{block.type === 'table' ? t("表格") : t("抽取文本")} {block.section}</summary><pre>{block.content}</pre></details>)}
      {!page?.blocks?.length && <pre>{page?.text || t("暂无逐页预览；重新解析可生成新版报告。")}</pre>}
      <details><summary>{t("索引片段 ")}{report.chunks_truncated ? t("（前 500 个）") : ''}</summary>{(report.chunks || []).filter(chunk => Number(chunk.page) === pageNumber).map(chunk => <article key={chunk.index}><small>{t("片段 ")}{chunk.index + 1} · {chunk.type}</small><pre>{chunk.content}</pre></article>)}</details>
    </details>
  </section>
}
