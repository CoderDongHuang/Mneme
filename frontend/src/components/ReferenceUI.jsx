import { useFormatters } from '../hooks/useFormatters'
import { dateKey, formatDate, parseInstant } from '../utils/dates'
import { useEffect, useState } from 'react'
import { X, CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { t, useI18n } from '../i18n'
import { SideDrawer } from './ui'
import { usePreferences } from '../state/PreferencesContext'

// A selected record stays alongside the list on a desktop; the same content
// becomes a keyboard-trapped dialog when there is insufficient reading space.
export function DetailPane({ open, title, onClose, busy, children, empty }) {
  useI18n()
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1279px)').matches)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 1279px)')
    const change = () => setNarrow(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  if (narrow) return <SideDrawer open={open} title={title} onClose={onClose} busy={busy}>{children}</SideDrawer>
  return <aside className="reference-detail" aria-label={title}><header><h2>{title}</h2>{open && <button className="icon-button" disabled={busy} onClick={onClose} aria-label={t('关闭 / Close')}><X size={18} /></button>}</header><div className="reference-detail-body">{open ? children : <div className="detail-placeholder">{empty || t('选择一条记录查看详情')}</div>}</div></aside>
}

export function MetricCards({ items }) {
  const fmt = useFormatters()
  return <div className="reference-metrics">{items.map(({ label, value, icon: Icon, note }) => <div key={label}>{Icon && <span className="metric-icon"><Icon size={22} strokeWidth={1.6} /></span>}<div><span>{label}</span><strong>{typeof value === 'number' ? fmt.number(value) : value}</strong>{note && <small>{note}</small>}</div></div>)}</div>
}

export function StudyCalendar({ cards = [] }) {
  useI18n()
  const { preferences } = usePreferences()
  const [week, setWeek] = useState(0)
  const today = dateKey(new Date(), preferences.timezone)
  // Calendar arithmetic is performed on the user's local calendar date.
  const anchor = new Date(`${today}T12:00:00Z`)
  const offset = (anchor.getUTCDay() + 6) % 7
  const dates = Array.from({ length: 7 }, (_, i) => { const d = new Date(anchor); d.setUTCDate(d.getUTCDate() - offset + i + week * 7); return d })
  const scheduled = cards.filter(card => parseInstant(card.due_at))
  return <section className="reference-calendar"><header><h3><CalendarDays size={18} />{t('复习日历')}</h3><div><button aria-label={t('上一周')} onClick={() => setWeek(v => v - 1)}><ChevronLeft size={16} /></button><button onClick={() => setWeek(0)}>{t('本周')}</button><button aria-label={t('下一周')} onClick={() => setWeek(v => v + 1)}><ChevronRight size={16} /></button></div></header><div className="calendar-days">{dates.map(date => { const key = date.toISOString().slice(0, 10); const count = scheduled.filter(card => dateKey(card.due_at, preferences.timezone) === key).length; return <div key={key} className={key === today ? 'today' : ''}><small>{formatDate(date, preferences.language, 'UTC', { weekday: 'short', year: undefined, month: undefined, day: undefined })}</small><strong>{date.getUTCDate()}</strong><span title={t('{0} 张', [count])}>{count ? '●' : '·'}</span></div> })}</div><p className="muted">{preferences.timezone}</p></section>
}
