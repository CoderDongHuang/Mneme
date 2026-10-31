// Legacy SQL/ISO timestamps without an offset are UTC, never browser-local.
export function parseInstant(value) {
  if (value == null || value === '') return null
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null
  const text = typeof value === 'string' ? value.trim().replace(' ', 'T') : value
  const normalized = typeof text === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text) ? `${text}Z` : text
  const date = new Date(normalized)
  return Number.isFinite(date.getTime()) ? date : null
}

export function formatDateTime(value, language = 'zh-CN', timezone = 'Asia/Shanghai', options = {}) {
  const date = parseInstant(value)
  if (!date) return '—'
  try {
    return new Intl.DateTimeFormat(language, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', ...options, timeZone: timezone }).format(date)
  } catch { return '—' }
}

export function formatDate(value, language, timezone, options = {}) {
  return formatDateTime(value, language, timezone, { year: 'numeric', month: 'short', day: 'numeric', hour: undefined, minute: undefined, ...options })
}

// Calendar dates (plans and daily aggregates) have no instant/timezone.
export function formatCalendarDate(value, language = 'zh-CN', options = {}) {
  const text = String(value || '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return '—'
  return formatDate(`${text}T12:00:00Z`, language, 'UTC', options)
}

export function dateKey(value, timezone = 'Asia/Shanghai') {
  const date = parseInstant(value)
  if (!date) return ''
  try {
    const parts = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: timezone }).formatToParts(date)
    const part = type => parts.find(item => item.type === type)?.value
    return `${part('year')}-${part('month')}-${part('day')}`
  } catch { return '' }
}
