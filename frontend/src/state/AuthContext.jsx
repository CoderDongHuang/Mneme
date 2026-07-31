import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { endpoints } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => JSON.parse(localStorage.getItem('mneme_auth') || 'null'))

  useEffect(() => {
    const logout = () => setSession(null)
    window.addEventListener('mneme:unauthorized', logout)
    return () => window.removeEventListener('mneme:unauthorized', logout)
  }, [])

  useEffect(() => {
    if (session) localStorage.setItem('mneme_auth', JSON.stringify(session))
    else localStorage.removeItem('mneme_auth')
  }, [session])

  const value = useMemo(() => ({
    session,
    async login(credentials) {
      const result = await endpoints.login(credentials)
      setSession(result)
      return result
    },
    async register(credentials) {
      const result = await endpoints.register(credentials)
      setSession(result)
      return result
    },
    updateSession(profile) {
      setSession((current) => current ? { ...current, ...profile } : current)
    },
    logout() {
      endpoints.logout().catch(() => {})
      setSession(null)
    },
  }), [session])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
