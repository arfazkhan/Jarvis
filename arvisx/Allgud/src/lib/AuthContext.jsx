import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { api, setToken, getToken } from '../api/client'

const AuthContext = createContext(null)

// Auth has three real states:
//  - open  : backend has no users + no API key → /auth/me returns role null, just proceed
//  - authed: a valid token (or API key) resolves to a role
//  - login : backend requires auth and we have no/expired token → 401 → show Login
export function AuthProvider({ children }) {
  const [status, setStatus] = useState('checking')  // checking | open | authed | login
  const [role, setRole] = useState(null)
  const [username, setUsername] = useState(null)
  const [error, setError] = useState(null)

  const check = useCallback(() => {
    setStatus('checking')
    return api
      .me()
      .then((res) => {
        // 200: a role means authed/API-key; null role = open dev mode (full access).
        if (res && res.role) {
          setRole(res.role)
          setUsername(res.username || null)
          setStatus('authed')
        } else {
          setRole('open')
          setUsername(null)
          setStatus('open')
        }
      })
      .catch((err) => {
        if (String(err.message).startsWith('401')) {
          setStatus('login')          // backend requires login
        } else {
          setError(err)               // API unreachable etc.
          setStatus('login')
        }
      })
  }, [])

  useEffect(() => {
    check()
  }, [check])

  const login = useCallback(
    async (user, password) => {
      const res = await api.login(user, password)   // { token, role, username }
      setToken(res.token)
      setRole(res.role)
      setUsername(res.username)
      setStatus('authed')
      return res
    },
    [],
  )

  // Field (technician) login — a short PIN, separate from the manager wall.
  // Mints the same Bearer token primitive a deep-link ?t= would, so both paths
  // land a technician in /field with identical handling.
  const fieldLogin = useCallback(async (building, pin) => {
    const res = await api.fieldLogin(building, pin)   // { token, role, technician }
    setToken(res.token)
    setRole(res.role)
    setUsername(res.technician)
    setStatus('authed')
    return res
  }, [])

  const logout = useCallback(() => {
    setToken('')
    setRole(null)
    setUsername(null)
    check()
  }, [check])

  // viewer is read-only; everyone else (owner/fm/system/open) can write.
  const canWrite = role !== 'viewer'

  return (
    <AuthContext.Provider
      value={{ status, role, username, canWrite, isTechnician: role === 'technician',
               error, login, fieldLogin, logout, retry: check, hasToken: !!getToken() }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
