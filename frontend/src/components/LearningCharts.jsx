import { t, useI18n } from '../i18n'
import { usePreferences } from '../state/PreferencesContext'

export function DailyChart({ rows = [], days = 30, line = false }) {
  useI18n()
  const { preferences } = usePreferences()
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: preferences.timezone }).format(new Date())
  const dates = Array.from({ length: days }, (_, index) => { const date = new Date(`${today}T12:00:00Z`); date.setUTCDate(date.getUTCDate() - days + 1 + index); return date.toISOString().slice(0, 10) })
  const values = dates.map(day => {
    const matches = rows.filter(row => String(row.day).slice(0, 10) === day)
    const observations = matches.reduce((sum, row) => sum + Number(row.observations || 0), 0)
    const value = line ? (observations ? matches.reduce((sum, row) => sum + Number(row.average_score || 0) * Number(row.observations || 0), 0) / observations : null) : observations
    return { day, value }
  })
  const max = line ? 100 : Math.max(4, ...values.map(item => item.value))
  const width = 520, height = 215, left = 35, top = 15, bottom = 185
  const x = i => left + (i + .5) * (width - left - 10) / days
  const y = value => bottom - value / max * (bottom - top)
  const points = values.flatMap((item, index) => item.value == null ? [] : [`${x(index)},${y(item.value)}`]).join(' ')
  const label = line ? t('每日平均分') : t('每日学习记录数')
  return <figure className="learning-chart"><figcaption>{line ? t('得分（满分 100）') : t('实际学习记录数')}</figcaption><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>{[0, .25, .5, .75, 1].map(tick => <g key={tick}><line x1={left} x2={width - 10} y1={y(tick * max)} y2={y(tick * max)} className="chart-grid"/><text x={left - 7} y={y(tick * max) + 4} textAnchor="end">{Math.round(tick * max)}</text></g>)}{line ? <><polyline points={points} fill="none" stroke="var(--mn-accent)" strokeWidth="2.5"/>{values.map((item, index) => item.value == null ? null : <circle key={item.day} cx={x(index)} cy={y(item.value)} r="3" fill="var(--mn-accent)"><title>{item.day}: {item.value.toFixed(1)}</title></circle>)}</> : values.map((item, index) => <rect key={item.day} x={x(index) - Math.max(1, (width - left) / days * .3)} y={y(item.value)} width={Math.max(2, (width - left) / days * .6)} height={bottom - y(item.value)} rx="1" fill="var(--mn-accent)" opacity=".78"><title>{item.day}: {item.value}</title></rect>)}{values.map((item, index) => index === 0 || index === days - 1 || index % Math.max(1, Math.round(days / 4)) === 0 ? <text key={item.day} x={x(index)} y={height - 9} textAnchor="middle">{item.day.slice(5)}</text> : null)}</svg>{!rows.length && <p className="chart-empty">{t('暂无样本')}</p>}<details><summary>{t('查看每日数据')}</summary><table><caption>{label}</caption><thead><tr><th>{t('日期')}</th><th>{label}</th></tr></thead><tbody>{values.map(item => <tr key={item.day}><td>{item.day}</td><td>{item.value == null ? '—' : line ? item.value.toFixed(1) : item.value}</td></tr>)}</tbody></table></details></figure>
}

export function ActivityCalendar({ rows = [] }) {
  useI18n()
  const { preferences } = usePreferences()
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: preferences.timezone }).format(new Date())
  const date = new Date(`${today}T12:00:00Z`)
  const first = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1, 12))
  const count = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate()
  const offset = (first.getUTCDay() + 6) % 7
  return <section className="analysis-panel activity-calendar"><h3>{t('学习活动')}</h3><p>{date.toLocaleDateString(preferences.language, { year: 'numeric', month: 'long', timeZone: 'UTC' })}</p><div className="month-grid">{Array.from({ length: 7 }, (_, index) => <small key={index}>{new Date(Date.UTC(2026, 0, 5 + index)).toLocaleDateString(preferences.language, { weekday: 'narrow', timeZone: 'UTC' })}</small>)}{Array.from({ length: offset }, (_, index) => <span key={`empty-${index}`}/>)}{Array.from({ length: count }, (_, index) => { const day = `${today.slice(0, 7)}-${String(index + 1).padStart(2, '0')}`; const observations = rows.filter(row => String(row.day).slice(0, 10) === day).reduce((sum, row) => sum + Number(row.observations || 0), 0); return <span key={day} className={`${observations ? 'has-activity' : ''} ${day === today ? 'today' : ''}`} title={`${day} · ${observations}`}>{index + 1}</span> })}</div><small>{t('仅标记所选窗口内的真实学习记录')}</small></section>
}
