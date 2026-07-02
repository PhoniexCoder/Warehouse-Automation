"use client"

import { useState, type ReactNode } from "react"
import { AuthProvider, useAuth } from "@/lib/auth"
import { Sidebar } from "./Sidebar"
import { PageLoader } from "@/components/ui/Spinner"

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  if (loading) return <PageLoader />
  if (!user) return null

  return (
    <div className="min-h-screen flex">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex-1 flex flex-col min-w-0">
        <header className="sticky top-0 z-20 bg-white/80 backdrop-blur-md border-b border-gray-200">
          <div className="flex items-center justify-between px-4 sm:px-6 py-3">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setSidebarOpen(true)}
                className="lg:hidden p-2 -ml-2 text-secondary hover:text-foreground rounded-lg hover:bg-gray-100"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
              <h1 className="text-lg font-semibold text-foreground hidden sm:block">Warehouse OS</h1>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-lg">
                <div className="w-7 h-7 bg-primary/10 text-primary rounded-full flex items-center justify-center text-xs font-semibold">
                  {user.username.charAt(0).toUpperCase()}
                </div>
                <span className="text-sm font-medium text-foreground hidden sm:block">{user.username}</span>
                <span className="badge bg-gray-200 text-secondary text-xs">{user.role}</span>
              </div>
              <button
                onClick={logout}
                className="p-2 text-secondary hover:text-danger rounded-lg hover:bg-danger-light/50 transition-colors"
                title="Logout"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            </div>
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 lg:p-8 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  )
}

export function withDashboard(Component: ReactNode) {
  return (
    <AuthProvider>
      <ProtectedLayout>{Component}</ProtectedLayout>
    </AuthProvider>
  )
}
