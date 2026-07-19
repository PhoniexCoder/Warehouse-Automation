"use client"

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react"
import { useRouter } from "next/navigation"
import { api } from "./api"
import type { User } from "./types"

interface AuthContextType {
  user: User | null
  loading: boolean
  isImpersonating: boolean
  originalUser: User | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  startImpersonation: (userId: string) => Promise<void>
  endImpersonation: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

function getStoredAdmin(): User | null {
  if (typeof window === "undefined") return null
  try {
    const raw = localStorage.getItem("admin_user")
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function setStoredAdmin(user: User | null) {
  if (user) {
    localStorage.setItem("admin_user", JSON.stringify(user))
  } else {
    localStorage.removeItem("admin_user")
  }
}

function getStoredAdminTokens(): { access: string; refresh: string } | null {
  if (typeof window === "undefined") return null
  const access = localStorage.getItem("admin_access_token")
  const refresh = localStorage.getItem("admin_refresh_token")
  if (access && refresh) return { access, refresh }
  return null
}

function setStoredAdminTokens(access: string, refresh: string) {
  localStorage.setItem("admin_access_token", access)
  localStorage.setItem("admin_refresh_token", refresh)
}

function clearStoredAdminTokens() {
  localStorage.removeItem("admin_access_token")
  localStorage.removeItem("admin_refresh_token")
}

function isImpersonatingSession(): boolean {
  if (typeof window === "undefined") return false
  return !!localStorage.getItem("admin_access_token")
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [isImpersonating, setIsImpersonating] = useState(false)
  const [originalUser, setOriginalUser] = useState<User | null>(null)
  const router = useRouter()

  const refreshUser = useCallback(async () => {
    try {
      const token = api.getToken()
      if (!token) {
        setUser(null)
        setLoading(false)
        return
      }
      const me = await api.getMe()
      api.setUser(me)
      setUser(me)

      if (isImpersonatingSession()) {
        setIsImpersonating(true)
        setOriginalUser(getStoredAdmin())
      }
    } catch {
      api.clearTokens()
      clearStoredAdminTokens()
      setStoredAdmin(null)
      setUser(null)
      setIsImpersonating(false)
      setOriginalUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshUser()
  }, [refreshUser])

  const login = useCallback(async (username: string, password: string) => {
    await api.login(username, password)
    const me = await api.getMe()
    api.setUser(me)
    setUser(me)
    router.push("/dashboard")
  }, [router])

  const logout = useCallback(() => {
    api.clearTokens()
    clearStoredAdminTokens()
    setStoredAdmin(null)
    setUser(null)
    setIsImpersonating(false)
    setOriginalUser(null)
    router.push("/login")
  }, [router])

  const startImpersonation = useCallback(async (userId: string) => {
    const adminUser = user
    if (!adminUser) return

    const result = await api.impersonateUser(userId)
    setStoredAdminTokens(result.access_token, result.refresh_token)
    setStoredAdmin(adminUser)

    localStorage.setItem("access_token", result.access_token)
    localStorage.setItem("refresh_token", result.refresh_token)

    const me = await api.getMe()
    api.setUser(me)
    setUser(me)
    setIsImpersonating(true)
    setOriginalUser(adminUser)
  }, [user])

  const endImpersonation = useCallback(() => {
    const adminTokens = getStoredAdminTokens()
    const adminUser = getStoredAdmin()
    if (!adminTokens || !adminUser) return

    localStorage.setItem("access_token", adminTokens.access)
    localStorage.setItem("refresh_token", adminTokens.refresh)
    clearStoredAdminTokens()
    setStoredAdmin(null)

    api.getMe().then((me) => {
      api.setUser(me)
      setUser(me)
      setIsImpersonating(false)
      setOriginalUser(null)
    }).catch(() => {
      logout()
    })
  }, [logout])

  return (
    <AuthContext.Provider value={{ user, loading, isImpersonating, originalUser, login, logout, startImpersonation, endImpersonation }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
