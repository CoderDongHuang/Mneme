import { useEffect, useRef, useState } from 'react'
import { MessageSquarePlus, Search, Sparkles, Trash2, X } from 'lucide-react'
import { FeedbackBlock } from '../../components/ui'
import LoadingState from '../../components/LoadingState'
import { useDateFormatter } from '../../hooks/useDateFormatter'
import { t } from '../../i18n'
import { parseInstant } from '../../utils/dates'

export default function ChatHistoryPanel({
  read, unavailable, activeSessionId, streaming, switching, deletingSessions,
  open, compact, sourceModalOpen, setOpen, onNew, onChoose, onRename, onDelete,
}) {
  const dates = useDateFormatter()
  const sessions = read.data || []
  const [query, setQuery] = useState('')
  const [date, setDate] = useState('')
  const [range, setRange] = useState(0)
  const [now] = useState(Date.now)
  const panelRef = useRef(null)

  useEffect(() => {
    if (!compact || !open) return
    const previous = document.activeElement
    const panel = panelRef.current
    panel.querySelector('button')?.focus()
    const keydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); setOpen(false) }
      if (event.key !== 'Tab') return
      const items = [...panel.querySelectorAll('button:not(:disabled),input,summary')].filter(item => item.getClientRects().length)
      const index = items.indexOf(document.activeElement)
      if (index < 0 || (event.shiftKey && index === 0) || (!event.shiftKey && index === items.length - 1)) {
        event.preventDefault()
        items[event.shiftKey ? items.length - 1 : 0]?.focus()
      }
    }
    panel.addEventListener('keydown', keydown)
    return () => {
      panel.removeEventListener('keydown', keydown)
      if (previous?.isConnected) previous.focus()
    }
  }, [compact, open, setOpen])

  const filteredSessions = sessions.filter(item => (
    (item.title || '').toLowerCase().includes(query.toLowerCase())
    && (!date || dates.dateKey(item.updatedAt || item.createdAt) === date)
    && (!range || now - (parseInstant(item.updatedAt || item.createdAt)?.getTime() ?? NaN) <= range * 86400000)
  ))

  return (
    <aside ref={panelRef} className="chat-history" role={compact && open ? 'dialog' : undefined}
      aria-modal={compact && open ? true : undefined} inert={!open || sourceModalOpen} aria-label={t('对话记录')}>
      <button className="history-close" onClick={() => setOpen(false)} aria-label={t('关闭会话栏')}>
        <X size={16} />{t('关闭会话栏')}
      </button>
      <div className="history-head">
        <div><strong>{t('对话历史')}</strong></div>
        <button onClick={onNew} title={t('新对话')} aria-label={t('新对话')}>
          <MessageSquarePlus size={16} /><span>{t('新建对话')}</span>
        </button>
      </div>
      <div className="history-filters">
        <label>
          <Search size={16} />
          <input aria-label={t('搜索会话')} placeholder={t('搜索对话…')} value={query} onChange={event => setQuery(event.target.value)} />
        </label>
        <div className="history-ranges">
          {[[0, '全部'], [7, '最近 7 天'], [30, '最近 30 天']].map(([days, label]) => (
            <button key={days} aria-pressed={range === days} onClick={() => { setRange(days); setDate('') }}>
              {t(label)}
              <small>{sessions.filter(item => !days || now - (parseInstant(item.updatedAt || item.createdAt)?.getTime() ?? NaN) <= days * 86400000).length}</small>
            </button>
          ))}
        </div>
        <details>
          <summary>{t('按日期筛选会话')}</summary>
          <input type="date" aria-label={t('按日期筛选会话')} value={date} onChange={event => setDate(event.target.value)} />
        </details>
      </div>
      <div className="history-list" role="region" aria-label={t('会话列表读取')} aria-busy={read.loading}>
        <FeedbackBlock error={read.error ? t('会话列表加载失败。已有记录可能不是最新状态，请重试。') : ''}
          onRetry={read.loading ? undefined : read.refresh} />
        {read.loading && <LoadingState />}
        {!read.loading && !read.error && <button onClick={read.refresh}>{t('刷新会话')}</button>}
        {filteredSessions.length ? filteredSessions.map(session => (
          <div key={session.id} className={`history-item ${activeSessionId === session.id ? 'active' : ''}`}>
            <button className="session-open" disabled={unavailable} aria-label={t('打开对话：{0}', [session.title || '新对话'])}
              onClick={() => onChoose(session)}>
              <strong>{session.title || t('新对话')}</strong><small>{dates.date(session.updatedAt || session.createdAt)}</small>
            </button>
            <button className="rename-session" disabled={streaming || switching || unavailable}
              title={t('重命名会话')} aria-label={t('重命名会话：{0}', [session.title])}
              onClick={() => onRename({ id: session.id, title: session.title || t('新对话') })}>✎</button>
            <button className="delete-session" disabled={streaming || switching || unavailable || deletingSessions.includes(session.id)}
              title={t('删除对话：{0}', [session.title || '新对话'])} aria-label={t('删除对话：{0}', [session.title || '新对话'])}
              onClick={event => onDelete(event, session)}><Trash2 size={15} /></button>
          </div>
        )) : !read.loading && !read.error && (
          <p className="history-empty">{t(sessions.length ? '没有符合筛选条件的对话' : '还没有历史对话')}</p>
        )}
      </div>
      <div className="history-foot"><Sparkles size={16} /><span>{t('从对话中积累学习记忆')}</span></div>
    </aside>
  )
}
