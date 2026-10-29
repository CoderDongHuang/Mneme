import { useSyncExternalStore } from 'react'
let english = {}
let requestedLanguage = 'zh-CN'
let catalogPromise

let language = 'zh-CN'
const listeners = new Set()
export async function setLanguage(value) {
  const next = value === 'en' ? 'en' : 'zh-CN'
  requestedLanguage = next
  if (next === 'en') {
    catalogPromise ??= import('./en.json').then(module => { english = module.default })
    await catalogPromise
    if (requestedLanguage !== next) return
  }
  if (next === language) return
  language = next
  listeners.forEach(listener => listener())
}
export function useI18n() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => listeners.delete(listener) }, () => language)
}

// Only UI messages call this function. Uploaded text, answers and user fields
// are never translated. Values are inserted after lookup, not used as keys.
export function t(key, values = []) {
  if (typeof key !== 'string') return key
  const trimmed = key.trim()
  const message = language === 'en' ? (english[key] ?? (english[trimmed] ? key.replace(trimmed, english[trimmed]) : key)) : key
  return message.replace(/\{(\d+)\}/g, (match, index) => values[index] ?? match)
}
