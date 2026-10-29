import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { documentFileUrl, endpoints } from '../api/client'
import { FeedbackBlock, SideDrawer } from './ui'
import ParsePreview from './ParsePreview'

export default function DocumentDetail({ document, onClose }) {
  useI18n();
  const [preview, setPreview] = useState(null)
  const [tab, setTab] = useState('original')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setPreview(null); setError(''); setTab('original')
    if (document) endpoints.documentPreview(document.id).then(value => { if (active) setPreview(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [document, retry])
  return <SideDrawer open={!!document} title={document?.fileName || t("文件详情")} onClose={onClose}>
    <FeedbackBlock error={error} onRetry={error ? () => setRetry(v => v + 1) : undefined} />
    {!preview && !error && <p role="status">{t("正在读取文件详情…")}</p>}
    {preview && <><nav className="segmented-tabs" aria-label={t("文件内容")}><button aria-pressed={tab === 'original'} onClick={() => setTab('original')}>{t("原文")}</button><button aria-pressed={tab === 'structure'} onClick={() => setTab('structure')}>{t("结构与 OCR")}</button><button aria-pressed={tab === 'chunks'} onClick={() => setTab('chunks')}>{t("索引片段")}</button></nav>
      <p className="muted">{t("任务状态：")}{document.status}{t(" · 解析质量见结构报告。任务完成不等于所有页面都正确解析。")}</p>
      {tab === 'original' && <><a className="text-link" href={documentFileUrl(document.id)} target="_blank" rel="noreferrer">{t("打开原文件")}</a><Link className="text-link" to={`/workspace?document=${document.id}`}>{t("在工作台阅读 →")}</Link><pre className="document-text">{preview.content || t("请打开原文件查看完整内容。")}</pre></>}
      {tab === 'structure' && <ParsePreview preview={preview} />}
      {tab === 'chunks' && <><p>{t("共 ")}{preview.parse_report?.chunk_count ?? document.chunkCount ?? 0}{t(" 个片段。")}{preview.parse_report?.chunks_truncated ? t("当前展示前 500 个片段。") : ''}</p>{(preview.parse_report?.chunks || []).map((chunk, index) => <article className="chunk-record" key={index}><Link to={`/workspace?document=${document.id}&page=${chunk.page || 1}&highlight=${encodeURIComponent((chunk.content || '').slice(0, 500))}`}>{t("片段 ")}{index + 1}{t(" · 第 ")}{chunk.page || '—'}{t(" 页")}</Link><pre>{chunk.content}</pre></article>)}{!preview.parse_report?.chunks?.length && <p>{t("暂无片段预览。任务完成后重新打开详情。")}</p>}</>}
    </>}
  </SideDrawer>
}
