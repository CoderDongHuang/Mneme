import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { endpoints } from '../api/client'

const AuthContext = createContext(null)

function storedSession() {
  try {
    return JSON.parse(localStorage.getItem('mneme_auth') || 'null')
  } catch {
    localStorage.removeItem('mneme_auth')
    return null
  }
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(storedSession)
  const [verifiedRole, setVerifiedRole] = useState(null)
  const userId = session?.userId
  useEffect(() => {
    setVerifiedRole(null)
    if (!userId) return
    let active = true
    endpoints.profile().then(profile => {
      if (active) { setVerifiedRole(profile.role || 'user'); setSession(current => current?.userId === userId ? { ...current, ...profile } : current) }
    }).catch(() => { if (active) setVerifiedRole('unavailable') })
    return () => { active = false }
  }, [userId])

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
    isAdmin: verifiedRole === 'admin',
    roleLoading: !!userId && verifiedRole === null,
    async login(credentials) {
      const result = await endpoints.login(credentials)
      localStorage.setItem('mneme_auth', JSON.stringify(result))
      setSession(result)
      return result
    },
    async register(credentials) {
      const result = await endpoints.register(credentials)
      localStorage.setItem('mneme_auth', JSON.stringify(result))
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
  }), [session, verifiedRole, userId])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
