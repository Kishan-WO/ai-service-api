import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null) // { user, tenant } when signed in
  const [loading, setLoading] = useState(Boolean(api.getToken()))

  const logout = useCallback(() => {
    api.setToken(null)
    setMe(null)
  }, [])

  // A 401 from any call (an expired token) signs the user out.
  useEffect(() => api.setUnauthorizedHandler(logout), [logout])

  useEffect(() => {
    if (!api.getToken()) return
    api
      .getMe()
      .then(setMe)
      .catch(() => api.setToken(null))
      .finally(() => setLoading(false))
  }, [])

  const finishSignIn = useCallback(async (tokenResponse) => {
    api.setToken(tokenResponse.access_token)
    setMe(await api.getMe())
  }, [])

  const value = useMemo(
    () => ({
      me,
      loading,
      logout,
      signIn: async (email, password) => finishSignIn(await api.login(email, password)),
      signUp: async (email, password, tenantName) =>
        finishSignIn(await api.register(email, password, tenantName)),
    }),
    [me, loading, logout, finishSignIn],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
