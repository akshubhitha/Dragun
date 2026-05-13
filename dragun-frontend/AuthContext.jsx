import { createContext, useContext, useState, useCallback } from 'react'

const AuthContext = createContext(null)

const SESSION_KEY = 'dragun_session'

function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) || '{}')
  } catch {
    return {}
  }
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(loadSession)

  const login = useCallback((user) => {
    const s = {
      user_id: user.user_id,
      handle: user.handle,
      email: user.email,
      session_token: user.session_token,
      monthly_income: user.monthly_income,
      fixed_costs_floor: user.fixed_costs_floor,
      utility_costs_avg: user.utility_costs_avg,
    }
    localStorage.setItem(SESSION_KEY, JSON.stringify(s))
    setSession(s)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(SESSION_KEY)
    setSession({})
  }, [])

  const updateSession = useCallback((fields) => {
    setSession(prev => {
      const next = { ...prev, ...fields }
      localStorage.setItem(SESSION_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const isAuthenticated = Boolean(session.user_id && session.session_token)

  return (
    <AuthContext.Provider value={{ session, isAuthenticated, login, logout, updateSession }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
