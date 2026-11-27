import { useEffect, useId, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Quote, X } from 'lucide-react'
import { useDateFormatter } from '../../hooks/useDateFormatter'
import { useFormatters } from '../../hooks/useFormatters'
import { t } from '../../i18n'

export default function ChatSourceDrawer({ sources, open, narrow, onClose, onError }) {
  const dates = useDateFormatter()
  const fmt = useFormatters()
  const navigate = useNavigate()
  const drawerRef = useRef(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    const drawer = drawerRef.current
    drawer.querySelector('button')?.focus()
    function keydown(event) {
      if (event.key === 'Escape') { event.preventDefault(); onClose() }
      if (event.key !== 'Tab' || !narrow) return
      const items = [...drawer.querySelectorAll('button:not(:disabled),a[href],summary')]
      const index = items.indexOf(document.activeElement)
      if (index < 0 || (event.shiftKey && index === 0) || (!event.shiftKey && index === items.length - 1)) {
        event.preventDefault()
        items[event.shiftKey ? items.length - 1 : 0]?.focus()
      }
    }
    drawer.addEventListener('keydown', keydown)
    return () => {
      drawer.removeEventListener('keydown', keydown)
      if (previous?.isConnected) previous.focus()
    }
  }, [open, narrow, onClose])

  /** @param {import("../../api/generated/chat-source").ChatSource} source */
  function openSource(source) {
    const documentId = String(source.document_id || '').replace(/^doc_/, '')
    if (!/^\d+$/.test(documentId)) return
    const params = new URLSearchParams({ document: documentId })
    if (source.page) params.set('page', String(source.page))
    if (source.content_sha256) params.set('sha256', source.content_sha256)
    if (source.chunk_content) params.set('highlight', source.chunk_content.slice(0, 500))
    navigate(`/workspace?${params.toString()}`)
    onClose()
  }

  if (narrow && !open) return null
  return (
    <aside ref={drawerRef} className="source-drawer" role={narrow ? "dialog" : "complementary"} aria-modal={narrow ? true : undefined} aria-labelledby={titleId}>
      <header>
        <div><strong id={titleId}>{t("引用与原文")}</strong></div>
        {narrow ? (
          <button title={t("关闭资料依据")} aria-label={t("关闭资料依据")} onClick={onClose}><X size={18} /></button>
        ) : <small>{t('{0} 条引用', [sources.length])}</small>}
      </header>
      {!sources.length && (
        <div className="source-empty">
          <Quote size={28} /><h3>{t('资料依据')}</h3>
          <p>{t('选择资料库并提问后，回答引用的原文会显示在这里。')}</p>
        </div>
      )}
      <div>{sources.map((source, index) => (
        <article key={`${source.document_id || source.document_name}-${index}`}>
          <div><span>{index + 1}</span><strong>{source.document_name}</strong></div>
          <small>{source.page ? t("第 {0} 页", [source.page]) : t("全文")}{source.section ? ` · ${source.section}` : ''}</small>
          <blockquote className="source-excerpt">{source.chunk_content}</blockquote>
          <div className="action-row">
            <button className="source-open" onClick={() => openSource(source)} disabled={!source.document_id}>{t("打开原文定位")}</button>
            <button onClick={async () => {
              try {
                await navigator.clipboard.writeText(`${source.document_name || source.document_id} · ${source.page || ''}\n${source.chunk_content || ''}`)
              } catch { onError(t('复制失败，请手动选择文本复制')) }
            }}>{t('复制引用')}</button>
          </div>
          <details>
            <summary>{t('来源信息')}</summary>
            {!!Object.keys(source.retrieval_ranks || {}).length && (
              <p className="source-signals">
                {t("召回路径：")}
                {Object.entries(source.retrieval_ranks).map(([channel, rank]) => `${channel.startsWith('dense:') ? t("向量") : t("词法")} #${rank}`).join(' · ')}
                {Number.isFinite(source.score) ? t(" · 排序信号 {0}（非可信概率）", [fmt.decimal(source.score, 3)]) : ''}
              </p>
            )}
            {source.indexed_at && <small>{t("索引时间：")}{dates.dateTime(source.indexed_at)}{t(" · 解析器 ")}{source.parser_version || t("未知")}</small>}
            {source.content_sha256 && <small title={source.content_sha256}>{t("文件版本 SHA-256：")}{source.content_sha256.slice(0, 16)}…</small>}
            <p className="muted">{t("资料依据需结合原文核验；排序信号不代表事实正确。")}</p>
          </details>
        </article>
      ))}</div>
    </aside>
  )
}
