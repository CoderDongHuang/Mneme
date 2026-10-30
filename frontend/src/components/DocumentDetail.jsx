import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, Minus, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { documentFileUrl, endpoints } from '../api/client'
import { FeedbackBlock } from './ui'
import { DetailPane } from './ReferenceUI'
import ParsePreview from './ParsePreview'

export default function DocumentDetail({ document, onClose }) {
  useI18n()
  const [preview, setPreview] = useState(null)
  const [tab, setTab] = useState('original')
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(100)
  const [imageError, setImageError] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const id = document?.id
  const revision = `${document?.updatedAt || ''}:${document?.status || ''}:${document?.parseReport || ''}`
  useEffect(() => {
    let active = true
    setPreview(null); setError(''); setTab('original'); setPage(1); setZoom(100); setImageError(false)
    if (id) endpoints.documentPreview(id).then(value => { if (active) setPreview(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [id, revision, retry])
  const pages = preview?.parse_report?.pages || []
  const count = Math.max(1, preview?.parse_report?.page_count || pages.length)
  const current = pages.find(item => Number(item.page) === page)
  const text = current?.text || current?.blocks?.map(block => block.content).join('\n\n') || preview?.content
  const hash = preview?.document?.sha256 || preview?.parse_report?.content_sha256
  const pageUrl = number => `/api/v1/workspace/documents/${id}/pages/${number}${hash ? `?sha256=${encodeURIComponent(hash)}` : ''}`
  return <DetailPane open={!!document} title={document?.fileName || t('文档预览')} onClose={onClose} empty={<><FileText size={32} /><p>{t('选择文件，查看原文与解析结果')}</p></>}>
    <FeedbackBlock error={error} onRetry={error ? () => setRetry(v => v + 1) : undefined} />
    {!preview && !error && document && <p role="status">{t('正在读取文件详情…')}</p>}
    {preview && <>
      <p className="document-summary">{preview.parse_report?.page_count || pages.length || '—'} {t('页/段')} · {preview.parse_report?.chunk_count ?? document.chunkCount ?? 0} {t('语义片段')}</p>
      <nav className="segmented-tabs document-preview-tabs" aria-label={t('文件内容')}>{[['original', '文档预览'], ['structure', '解析结构'], ['chunks', '检索片段']].map(([key, label]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{t(label)}</button>)}</nav>
      {tab === 'original' && <>
        <div className="document-preview-stage"><div className="paper-viewport">{preview.extension === 'pdf' && !imageError ? <img className="actual-page" src={pageUrl(page)} onError={() => setImageError(true)} alt={t('第 {0} 页', [page])} style={{ width: `${zoom}%` }} /> : preview.extension === 'pdf' ? <iframe className="document-frame" src={documentFileUrl(id, page, hash)} title={document.fileName} /> : <article className="document-paper" style={{ fontSize: `${zoom}%` }}><h3>{document.fileName}</h3><pre>{text || t('请打开原文件查看完整内容。')}</pre><small>{page}</small></article>}</div>
          {pages.length > 1 && <nav className="page-thumbnails" aria-label={t('文档页码')}>{pages.slice(0, 100).map(item => <button key={item.page} aria-current={page === Number(item.page) ? 'page' : undefined} onClick={() => { setPage(Number(item.page)); setImageError(false) }}>{preview.extension === 'pdf' ? <img loading="lazy" src={pageUrl(item.page)} alt="" /> : <span>{item.text || item.blocks?.map(block => block.content).join(' ') || document.fileName}</span>}<small>{item.page}</small></button>)}</nav>}
        </div>
        <div className="page-navigation"><button aria-label={t('上一页')} disabled={page <= 1} onClick={() => { setPage(v => v - 1); setImageError(false) }}><ChevronLeft size={17} /></button><span>{page} / {count}</span><button aria-label={t('下一页')} disabled={page >= count} onClick={() => { setPage(v => v + 1); setImageError(false) }}><ChevronRight size={17} /></button><button aria-label={t('缩小')} disabled={zoom <= 70} onClick={() => setZoom(v => v - 10)}><Minus size={16} /></button><span>{zoom}%</span><button aria-label={t('放大')} disabled={zoom >= 180} onClick={() => setZoom(v => v + 10)}><Plus size={16} /></button></div>
        <div className="action-row"><a className="text-link" href={documentFileUrl(id)} target="_blank" rel="noreferrer">{t('打开原文件')}</a><Link className="text-link" to={`/workspace?document=${id}&page=${page}`}>{t('在工作台阅读 →')}</Link></div>
        {!!preview.parse_report?.chunks?.length && <section className="preview-excerpt"><h3>{t('相关检索片段')}</h3><p>{preview.parse_report.chunks.find(chunk => Number(chunk.page) === page)?.content || t('本页暂无索引片段')}</p></section>}
      </>}
      {tab === 'structure' && <ParsePreview preview={preview} initialPage={page} />}
      {tab === 'chunks' && <><p>{t('共 ')}{preview.parse_report?.chunk_count ?? document.chunkCount ?? 0}{t(' 个片段。')}{preview.parse_report?.chunks_truncated ? t('当前展示前 500 个片段。') : ''}</p>{(preview.parse_report?.chunks || []).map((chunk, index) => <article className="chunk-record" key={index}><Link to={`/workspace?document=${id}&page=${chunk.page || 1}&highlight=${encodeURIComponent((chunk.content || '').slice(0, 500))}`}>{t('片段 ')}{index + 1}{t(' · 第 ')}{chunk.page || '—'}{t(' 页')}</Link><pre>{chunk.content}</pre></article>)}{!preview.parse_report?.chunks?.length && <p>{t('暂无片段预览。任务完成后重新打开详情。')}</p>}</>}
    </>}
  </DetailPane>
}
