import { expect, test } from 'vitest'
import { dateKey, formatCalendarDate, formatDateTime, parseInstant } from './dates'

test('legacy UTC and explicit offsets identify the same instant regardless of browser zone', () => {
  const expected = '2026-10-30T23:30:00.000Z'
  for (const value of ['2026-10-30 23:30:00', '2026-10-30T23:30:00', '2026-10-31T07:30:00+08:00']) {
    expect(parseInstant(value).toISOString()).toBe(expected)
    expect(dateKey(value, 'Asia/Shanghai')).toBe('2026-10-31')
    expect(dateKey(value, 'Europe/Amsterdam')).toBe('2026-10-31')
    expect(dateKey(value, 'America/New_York')).toBe('2026-10-30')
  }
})

test('Amsterdam observes both spring and autumn DST transitions', () => {
  const time = value => formatDateTime(value, 'en-GB', 'Europe/Amsterdam', { hourCycle: 'h23' })
  expect(time('2026-03-29T00:30:00Z')).toContain('01:30')
  expect(time('2026-03-29T01:30:00Z')).toContain('03:30')
  expect(time('2026-10-25T00:30:00Z')).toContain('02:30')
  expect(time('2026-10-25T01:30:00Z')).toContain('02:30')
})

test('locale and timezone affect display, while calendar deadlines keep their day', () => {
  const value = '2026-10-30T18:30:00Z'
  expect(formatDateTime(value, 'en', 'Europe/Amsterdam')).toContain('Oct 30, 2026')
  expect(formatDateTime(value, 'en', 'Europe/Amsterdam')).toContain('07:30')
  expect(formatDateTime(value, 'zh-CN', 'Asia/Shanghai')).toContain('2026年10月31日')
  expect(formatDateTime(value, 'zh-CN', 'Asia/Shanghai')).toContain('02:30')
  expect(formatCalendarDate('2026-10-30', 'en')).toBe('Oct 30, 2026')
  expect(formatCalendarDate('2026-10-30', 'zh-CN')).toBe('2026年10月30日')
})

test('missing, malformed timestamps and invalid preferences have safe fallbacks', () => {
  for (const value of [null, '', 'broken', new Date(NaN)]) {
    expect(parseInstant(value)).toBeNull()
    expect(formatDateTime(value)).toBe('—')
    expect(dateKey(value)).toBe('')
  }
  expect(formatDateTime('2026-10-30T00:00Z', 'en', 'Invalid/Zone')).toBe('—')
})
