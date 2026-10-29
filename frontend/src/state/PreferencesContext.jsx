import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'
import { useAuth } from './AuthContext'
import { setLanguage } from '../i18n'

const defaults = { language: 'zh-CN', timezone: 'Asia/Shanghai', notifications: true, theme: 'system' }
function normalize(value = {}) {
  return { ...defaults, ...value, language: value.language === 'en' ? 'en' : 'zh-CN', theme: ['light', 'dark', 'system'].includes(value.theme) ? value.theme : 'system' }
}
function guestPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem('mneme:guest-preferences') || '{}')
    return { ...defaults, language: value.language === 'en' ? 'en' : 'zh-CN', theme: ['light', 'dark', 'system'].includes(value.theme) ? value.theme : 'system' }
  } catch { return defaults }
}
const Context = createContext({ preferences: defaults, save: async () => {} })
export function PreferencesProvider({ children }) {
  const { session } = useAuth()
  const userId = session?.userId
  const owner = useRef(userId)
  useEffect(() => { owner.current = userId }, [userId])
  const [stored, setStored] = useState(() => ({ owner: userId, value: userId ? defaults : guestPreferences() }))
  const preferences = stored.owner === userId ? stored.value : userId ? defaults : guestPreferences()
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    if (userId) endpoints.preferences().then(value => { if (active) { setStored({ owner: userId, value: normalize(value) }); setError('') } }).catch(failure => { if (active) setError(failure.message) })
    else { setStored({ owner: userId, value: guestPreferences() }); setError('') }
    return () => { active = false }
  }, [userId])
  useEffect(() => {
    document.documentElement.lang = preferences.language
    setLanguage(preferences.language).catch(() => setError('Language resources could not be loaded. Please reload.'))
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => { document.documentElement.dataset.theme = preferences.theme === 'system' ? (media.matches ? 'dark' : 'light') : preferences.theme }
    apply(); media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [preferences])
  async function save(value) {
    const requestingUser = userId
    const saved = normalize(userId ? await endpoints.savePreferences(value) : value)
    if (owner.current === requestingUser) {
      await setLanguage(saved.language)
      if (owner.current !== requestingUser) return saved
      setStored({ owner: requestingUser, value: saved }); setError('')
      if (!userId) { try { localStorage.setItem('mneme:guest-preferences', JSON.stringify(saved)) } catch { /* Storage may be disabled. */ } }
    }
    return saved
  }
  return <Context.Provider value={{ preferences, save, error }}>{children}</Context.Provider>
}
export function usePreferences() { return useContext(Context) }
