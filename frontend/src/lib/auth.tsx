import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  accessToken,
  authApi,
  clearSession,
  refreshAccessToken,
  SESSION_CLEARED_EVENT,
  setAccessToken,
  type User,
} from './api'

interface AuthContextValue {
  user: User | null
  loading: boolean
  isAuthenticated: boolean
  isAdmin: boolean
  login: (email: string, password: string) => Promise<User>
  register: (email: string, password: string, fullName?: string) => Promise<User>
  logout: () => Promise<void>
  refreshUser: () => Promise<User | null>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function storedUser(): User | null {
  try {
    const raw = localStorage.getItem('user')
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    localStorage.removeItem('user')
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(storedUser)
  const [loading, setLoading] = useState(true)

  const persistUser = useCallback((next: User | null) => {
    setUser(next)
    if (next) localStorage.setItem('user', JSON.stringify(next))
    else localStorage.removeItem('user')
  }, [])

  const refreshUser = useCallback(async () => {
    try {
      if (!accessToken()) await refreshAccessToken()
      const current = await authApi.me()
      persistUser(current)
      return current
    } catch {
      persistUser(null)
      return null
    }
  }, [persistUser])

  useEffect(() => {
    let active = true
    void refreshAccessToken()
      .then(() => authApi.me())
      .then((current) => {
        if (active) persistUser(current)
      })
      .catch(() => {
        if (active) persistUser(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [persistUser])

  useEffect(() => {
    const onSessionCleared = () => {
      persistUser(null)
      setLoading(false)
    }
    window.addEventListener(SESSION_CLEARED_EVENT, onSessionCleared)
    return () => window.removeEventListener(SESSION_CLEARED_EVENT, onSessionCleared)
  }, [persistUser])

  useEffect(() => {
    const syncSession = (event: StorageEvent) => {
      if (event.key === 'academic-cluster:session-event') persistUser(null)
      if (event.key === 'user') persistUser(storedUser())
    }
    window.addEventListener('storage', syncSession)
    return () => window.removeEventListener('storage', syncSession)
  }, [persistUser])

  const login = useCallback(
    async (email: string, password: string) => {
      setLoading(true)
      try {
        const tokens = await authApi.login(email, password)
        setAccessToken(tokens.access_token)
        const current = await authApi.me()
        persistUser(current)
        return current
      } catch (error) {
        clearSession()
        throw error
      } finally {
        setLoading(false)
      }
    },
    [persistUser],
  )

  const register = useCallback(
    async (email: string, password: string, fullName?: string) => {
      setLoading(true)
      try {
        await authApi.register(email, password, fullName)
        const tokens = await authApi.login(email, password)
        setAccessToken(tokens.access_token)
        const current = await authApi.me()
        persistUser(current)
        return current
      } catch (error) {
        clearSession()
        throw error
      } finally {
        setLoading(false)
      }
    },
    [persistUser],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Local logout remains available when the API is offline.
    }
    clearSession()
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAuthenticated: Boolean(user && accessToken()),
      isAdmin: user?.role === 'admin',
      login,
      register,
      logout,
      refreshUser,
    }),
    [loading, login, logout, refreshUser, register, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
