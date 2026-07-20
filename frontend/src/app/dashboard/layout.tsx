"use client"

import { AuthProvider, useAuth } from "@/lib/auth"
import { api } from "@/lib/api"
import type { ReactNode } from "react"
import { useState, useRef, useEffect } from "react"
import { PageLoader } from "@/components/ui/Spinner"
import { Button } from "@/components/ui/Button"
import { Modal } from "@/components/ui/Modal"
import Link from "next/link"
import { usePathname } from "next/navigation"
import clsx from "clsx"

const navItems = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/inventory", label: "Inventory" },
  { href: "/dashboard/cameras", label: "Cameras & NVRs" },
  { href: "/dashboard/warehouses", label: "Warehouses" },
  { href: "/dashboard/users", label: "Users" },
  { href: "/dashboard/alerts", label: "Alerts" },
]

function DashboardShell({ children }: { children: ReactNode }) {
  const { user, loading, logout, isImpersonating, originalUser, endImpersonation } = useAuth()
  const pathname = usePathname()
  const [profileOpen, setProfileOpen] = useState(false)
  const [pwModalOpen, setPwModalOpen] = useState(false)
  const [currentPw, setCurrentPw] = useState("")
  const [newPw, setNewPw] = useState("")
  const [confirmPw, setConfirmPw] = useState("")
  const [pwSaving, setPwSaving] = useState(false)
  const [pwError, setPwError] = useState("")
  const [pwSuccess, setPwSuccess] = useState("")
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setProfileOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  async function handleChangePassword() {
    setPwError("")
    setPwSuccess("")
    if (!currentPw || !newPw) {
      setPwError("All fields are required")
      return
    }
    if (newPw.length < 8) {
      setPwError("New password must be at least 8 characters")
      return
    }
    if (newPw !== confirmPw) {
      setPwError("New passwords do not match")
      return
    }
    setPwSaving(true)
    try {
      await api.changePassword({ current_password: currentPw, new_password: newPw })
      setPwSuccess("Password changed successfully")
      setCurrentPw("")
      setNewPw("")
      setConfirmPw("")
      setTimeout(() => { setPwModalOpen(false); setPwSuccess("") }, 1500)
    } catch {
      setPwError("Current password is incorrect")
    } finally {
      setPwSaving(false)
    }
  }

  if (loading) return <PageLoader />
  if (!user) return null

  const displayRole = user.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1).toLowerCase() : "Operator"
  const isAdmin = user.role === "SUPER_ADMIN" || user.role === "ADMIN"

  const filteredNavItems = isAdmin
    ? [...navItems, { href: "/dashboard/users", label: "Users" }]
    : navItems

  return (
    <div className="min-h-screen bg-[#f5f7fa] text-slate-800 flex flex-col font-sans">
      
      {/* Impersonation Banner */}
      {isImpersonating && originalUser && (
        <div className="bg-amber-500 text-white px-4 py-2 flex items-center justify-center gap-3 text-sm font-medium z-30 relative">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
          </svg>
          <span>
            Viewing as <strong>{user?.username}</strong> ({displayRole})
          </span>
          <button
            onClick={endImpersonation}
            className="ml-2 px-3 py-0.5 bg-white/20 hover:bg-white/30 rounded-full text-xs font-bold transition-colors cursor-pointer"
          >
            Switch Back
          </button>
        </div>
      )}

      {/* Top Header Navigation */}
      <header className="sticky top-0 z-20 bg-white/80 backdrop-blur-md border-b border-slate-200/60 shadow-[0_2px_15px_rgba(0,0,0,0.015)]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          
          {/* Vistock Brand Orange-Yellow-Red gradient logo */}
          <div className="flex items-center gap-2.5 shrink-0">
            <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-yellow-400 via-orange-500 to-red-600 shadow-[0_0_12px_rgba(249,115,22,0.35)]" />
            <span className="text-base font-black text-slate-900 tracking-tight">
              Vistock <span className="text-orange-500">Warehouse</span>
            </span>
          </div>

          {/* Center: Pill Navigation Menu (hidden on mobile, expandable menu on mobile optional) */}
          <nav className="hidden md:flex items-center bg-[#f1f3f7] p-1 rounded-full border border-slate-200/50">
            {navItems
              .filter((item) => {
                if (item.href === "/dashboard/users") {
                  return user.role === "ADMIN" || user.role === "SUPER_ADMIN"
                }
                return true
              })
              .map((item) => {
              // Active status checks if route starts with the link
              const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href))
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "px-4 py-1.5 rounded-full text-xs font-semibold tracking-wide transition flex items-center gap-1.5",
                    active 
                      ? "bg-white text-slate-900 shadow-[0_2px_6px_rgba(0,0,0,0.04)] border border-slate-100/50" 
                      : "text-slate-500 hover:text-slate-800"
                  )}
                >
                  {active && <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />}
                  {item.label}
                </Link>
              )
            })}
          </nav>

          {/* Right: Search, Notifications, Profile Card */}
          <div className="flex items-center gap-4 shrink-0">
            
            {/* Notifications Button */}
            <div className="relative">
              <Link
                href="/dashboard/alerts"
                className="p-2 block text-slate-500 hover:text-slate-900 rounded-full hover:bg-slate-100 transition-colors"
                title="Alerts"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full border border-white" />
              </Link>
            </div>

            {/* Profile Avatar Card */}
            <div className="relative" ref={menuRef}>
              <button
                onClick={() => setProfileOpen(!profileOpen)}
                className="flex items-center gap-2 px-3 py-1 bg-slate-50 hover:bg-slate-100/80 rounded-xl border border-slate-150 transition cursor-pointer"
              >
                <div className="w-7 h-7 bg-blue-600 text-white rounded-full flex items-center justify-center text-xs font-bold shadow-sm shadow-blue-500/20">
                  {user.username.charAt(0).toUpperCase()}
                </div>
                <div className="hidden sm:flex flex-col text-left">
                  <span className="text-xs font-bold text-slate-900 leading-none">{user.username}</span>
                  <span className="text-[9px] font-bold text-slate-400 font-mono tracking-wide mt-0.5 uppercase leading-none">{displayRole}</span>
                </div>
                <svg className="w-3.5 h-3.5 text-slate-400 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {profileOpen && (
                <div className="absolute right-0 top-full mt-1 w-48 bg-white rounded-xl border border-slate-200 shadow-lg py-1 z-50">
                  <button
                    onClick={() => { setProfileOpen(false); setPwModalOpen(true) }}
                    className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2 transition-colors"
                  >
                    <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                    </svg>
                    Change Password
                  </button>
                  <div className="border-t border-slate-100 my-1" />
                  <button
                    onClick={logout}
                    className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                    </svg>
                    Logout
                  </button>
                </div>
              )}
            </div>

          </div>
        </div>

        {/* Mobile Navigation Row */}
        <div className="md:hidden border-t border-slate-100 bg-white/95 py-2 overflow-x-auto whitespace-nowrap scrollbar-none">
          <div className="flex items-center px-4 gap-2">
            {navItems
              .filter((item) => {
                if (item.href === "/dashboard/users") {
                  return user.role === "ADMIN" || user.role === "SUPER_ADMIN"
                }
                return true
              })
              .map((item) => {
              const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href))
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "px-3.5 py-1.5 rounded-full text-xs font-bold transition inline-block",
                    active 
                      ? "bg-slate-100 text-slate-900" 
                      : "text-slate-500 hover:text-slate-800"
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>

      {/* Change Password Modal */}
      <Modal open={pwModalOpen} onClose={() => setPwModalOpen(false)} title="Change Password" size="sm">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Current Password</label>
            <input
              type="password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              className="input-field"
              placeholder="Enter current password"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">New Password</label>
            <input
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              className="input-field"
              placeholder="At least 8 characters"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Confirm New Password</label>
            <input
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              className="input-field"
              placeholder="Repeat new password"
            />
          </div>
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwSuccess && <p className="text-sm text-green-600">{pwSuccess}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setPwModalOpen(false)}>Cancel</Button>
            <Button onClick={handleChangePassword} loading={pwSaving}>Change Password</Button>
          </div>
        </div>
      </Modal>

    </div>
  )
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <DashboardShell>{children}</DashboardShell>
    </AuthProvider>
  )
}
