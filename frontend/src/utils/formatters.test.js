import { expect, test } from 'vitest'
import { formatBytes, formatDecimal, formatMoney, formatNumber, formatPercent, formatTokens } from './formatters'
import { statusLabel } from './statuses'

test('missing and invalid measurements never become zero, NaN or Infinity', () => {
  for (const value of [undefined, null, '', ' ', false, true, {}, [], NaN, Infinity, '-Infinity', '12px', '0x10']) {
    for (const format of [formatNumber, formatDecimal, formatPercent, formatBytes, formatTokens]) expect(format(value)).toBe('—')
  }
  expect(formatNumber(0)).toBe('0')
  expect(formatPercent(0)).toBe('0.0%')
  expect(formatBytes(0)).toBe('0 B')
})

test('locale, fixed precision and ratio percentages are consistent', () => {
  expect(formatNumber('1234567.89', 'en')).toBe('1,234,567.89')
  expect(formatNumber(1234567.89, 'de-DE')).toBe('1.234.567,89')
  expect(formatDecimal(0.12345, 'en', 3)).toBe('0.123')
  expect(formatDecimal('1e3', 'en')).toBe('1,000.0')
  expect(formatPercent(.125, 'en')).toBe('12.5%')
  expect(formatPercent(.125, 'de-DE')).toMatch(/^12,5\s%$/)
  expect(formatPercent(1, 'zh-CN', 0)).toBe('100%')
  expect(formatPercent(-.05, 'en')).toBe('-5.0%')
})

test('byte units use IEC boundaries and do not round to 1024 of the smaller unit', () => {
  for (const language of ['zh-CN', 'en']) {
    expect(formatBytes(1023, language)).toBe('1,023 B')
    expect(formatBytes(1024, language)).toBe('1 KiB')
    expect(formatBytes(1536, language)).toBe('1.5 KiB')
    expect(formatBytes(1024 ** 2 - 1, language)).toBe('1 MiB')
    expect(formatBytes(1024 ** 3, language)).toBe('1 GiB')
    expect(formatBytes(-1, language)).toBe('—')
  }
  expect(formatBytes(1536, 'de-DE')).toBe('1,5 KiB')
})

test('token counts preserve large integers and reject fractional, negative or unsafe counts', () => {
  expect(formatTokens(1234567, 'en')).toBe('1,234,567')
  expect(formatTokens(12345678901234567890n, 'en')).toBe('12,345,678,901,234,567,890')
  for (const value of [-1, .1, Number.MAX_SAFE_INTEGER + 1]) expect(formatTokens(value)).toBe('—')
})

test('money requires an explicit currency and distinguishes bills, estimates and test budgets', () => {
  expect(formatMoney(1.25, { currency: 'USD', kind: 'billed' }, 'en')).toMatch(/^USD\s1\.25 · Provider bill$/)
  expect(formatMoney(.000123, { currency: 'USD', kind: 'estimated' }, 'en')).toContain('0.000123 · Estimated cost')
  expect(formatMoney(1000, { currency: 'CNY', kind: 'test_budget' }, 'zh-CN')).toContain('1,000.00 · 测试预算')
  for (const options of [undefined, { currency: 'USD' }, { kind: 'billed' }, { currency: 'USD', kind: 'unknown' }, { currency: 'USD', kind: 'constructor' }]) expect(formatMoney(10, options)).toBe('—')
  expect(formatMoney(null, { currency: 'USD', kind: 'billed' })).toBe('—')
})

test('status names preserve their domain and do not hide unknown server states', () => {
  expect(statusLabel('processing', 'document')).toBe('解析中')
  expect(statusLabel('processing', 'task')).toBe('执行中')
  expect(statusLabel('ready', 'service')).toBe('正常')
  expect(statusLabel('ready', 'document')).toBe('可检索')
  expect(statusLabel('completed')).toBe('已完成')
  expect(statusLabel('future_state')).toBe('future_state')
  expect(statusLabel('constructor')).toBe('constructor')
  expect(statusLabel('ready', '__proto__')).toBe('ready')
  expect(statusLabel(null)).toBe('未知')
})
