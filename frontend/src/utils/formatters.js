// Display values only. IDs, API payloads, CSS coordinates and calculations stay raw.
const missing = '—'

function numeric(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string' || !value.trim() || !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null
  const result = Number(value)
  return Number.isFinite(result) ? result : null
}

export function formatNumber(value, language = 'zh-CN', options = {}) {
  const number = typeof value === 'bigint' ? value : numeric(value)
  if (number == null) return missing
  return new Intl.NumberFormat(language, { maximumFractionDigits: 2, ...options }).format(number)
}

export function formatDecimal(value, language = 'zh-CN', digits = 1) {
  return formatNumber(value, language, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

// Input is always a ratio (0.125 → 12.5%), never an already multiplied percent.
export function formatPercent(value, language = 'zh-CN', digits = 1) {
  return formatNumber(value, language, { style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatBytes(value, language = 'zh-CN', digits = 2) {
  const bytes = numeric(value)
  if (bytes == null || bytes < 0) return missing
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  let unit = bytes === 0 ? 0 : Math.min(units.length - 1, Math.max(0, Math.floor(Math.log(bytes) / Math.log(1024))))
  if (unit < units.length - 1 && Number((bytes / 1024 ** unit).toFixed(digits)) >= 1024) unit++
  return `${formatNumber(bytes / 1024 ** unit, language, { maximumFractionDigits: unit ? digits : 0 })} ${units[unit]}`
}

export function formatTokens(value, language = 'zh-CN') {
  const number = typeof value === 'bigint' ? value : numeric(value)
  return number != null && number >= 0 && (typeof number === 'bigint' || Number.isSafeInteger(number))
    ? formatNumber(number, language, { maximumFractionDigits: 0 }) : missing
}

// No default currency or provenance: an estimate must never look like an invoice.
export function formatMoney(value, { currency, kind } = {}, language = 'zh-CN') {
  const labels = language.startsWith('en')
    ? { billed: 'Provider bill', estimated: 'Estimated cost', test_budget: 'Test budget' }
    : { billed: '供应商账单', estimated: '估算成本', test_budget: '测试预算' }
  if (!/^[A-Z]{3}$/.test(currency || '') || !Object.hasOwn(labels, kind) || numeric(value) == null) return missing
  return `${formatNumber(value, language, { style: 'currency', currency, currencyDisplay: 'code', maximumFractionDigits: 6 })} · ${labels[kind]}`
}
