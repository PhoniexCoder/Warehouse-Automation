"use client"

import { useState, type FormEvent } from "react"
import { AuthProvider, useAuth } from "@/lib/auth"

function LoginForm() {
  const { login } = useAuth()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError("Please enter both username and password")
      return
    }
    setError("")
    setLoading(true)
    try {
      await login(username, password)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Invalid credentials"
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen grid grid-cols-1 lg:grid-cols-12 bg-[#13151a] text-slate-100 font-sans overflow-hidden select-none">
      
      {/* Left Panel: Login Form (7 columns on desktop) */}
      <div className="lg:col-span-7 flex flex-col justify-between p-8 sm:p-12 md:p-16 relative z-10 min-h-screen">
        
        {/* Top Header Bar */}
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-3">
            {/* Blue spherical gradient logo */}
            <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-blue-600 via-blue-500 to-cyan-400 shadow-[0_0_15px_rgba(59,130,246,0.4)]" />
            <span className="text-lg font-bold text-white tracking-tight">
              Vistock<span className="text-blue-500">.</span>
            </span>
          </div>
        </div>

        {/* Central Form Content Container */}
        <div className="my-auto max-w-md w-full mx-auto lg:mx-0 lg:pl-12 xl:pl-20 py-12">
          
          <p className="text-xs font-bold tracking-wider text-slate-500 uppercase mb-2">
            START FOR FREE
          </p>
          <h1 className="text-4xl sm:text-5xl font-bold text-white tracking-tight leading-tight mb-3">
            Sign in to account<span className="text-blue-500">.</span>
          </h1>
          <p className="text-sm text-slate-400 mb-8 font-medium">
            Not a member? <a href="#" className="text-blue-500 hover:text-blue-400 hover:underline transition">Request access</a>
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="flex items-start gap-3 p-4 bg-red-950/20 border border-red-500/20 text-red-200 text-xs rounded-2xl mb-2 animate-fade-in">
                <svg className="w-4 h-4 shrink-0 text-red-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <div className="font-mono">
                  <span className="font-bold text-red-400">ERROR //</span> {error}
                </div>
              </div>
            )}

            <div>
              <label htmlFor="username" className="block text-xs font-semibold text-slate-400 mb-2 px-1">
                Operator Username
              </label>
              <div className="relative flex items-center bg-[#1c202a] border border-transparent rounded-xl px-4 py-3.5 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20 transition duration-200">
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-transparent border-none outline-none text-sm !text-white placeholder-slate-500 focus:ring-0"
                  placeholder="Enter credential ID"
                  autoComplete="username"
                  autoFocus
                />
                <svg className="w-5 h-5 text-slate-500 shrink-0 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-xs font-semibold text-slate-400 mb-2 px-1">
                System Password
              </label>
              <div className="relative flex items-center bg-[#1c202a] border border-transparent rounded-xl px-4 py-3.5 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20 transition duration-200">
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-transparent border-none outline-none text-sm !text-white placeholder-slate-500 focus:ring-0"
                  placeholder="••••••••••••"
                  autoComplete="current-password"
                />
                <svg className="w-5 h-5 text-slate-500 shrink-0 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </div>
            </div>

            <div className="flex items-center gap-4 pt-2">
              <button
                type="button"
                className="flex-1 sm:flex-initial bg-[#252a37] hover:bg-[#2d3445] text-slate-200 py-3.5 px-8 rounded-full text-sm font-semibold transition active:scale-[0.98]"
              >
                Reset Password
              </button>
              <button
                type="submit"
                disabled={loading}
                className="flex-1 sm:flex-initial bg-blue-500 hover:bg-blue-600 text-white py-3.5 px-8 rounded-full text-sm font-semibold transition active:scale-[0.98] shadow-[0_4px_15px_rgba(59,130,246,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Signing in..." : "Sign in"}
              </button>
            </div>
          </form>

        </div>

        {/* Footer */}
        <div className="w-full">
          <p className="text-xs text-slate-500">
            © 2026 Vistock. Authorized operations only.
          </p>
        </div>

      </div>

      {/* Right Panel: Warehouse Cover Image (5 columns on desktop, hidden on mobile) */}
      <div className="lg:col-span-5 relative h-full hidden lg:flex items-end justify-end p-12 overflow-hidden bg-[#13151a]">
        
        {/* Warehouse Background Image Asset */}
        <div 
          className="absolute inset-0 bg-cover bg-center bg-no-repeat opacity-55"
          style={{ backgroundImage: 'url("/warehouse-bg.png")' }}
        />
        {/* Left Fade Overlay (blends image into the left dark panel) */}
        <div className="absolute inset-0 bg-gradient-to-r from-[#13151a] via-[#13151a]/30 to-transparent z-10" />
        
        {/* Bottom Dark shading overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-[#13151a] via-transparent to-transparent opacity-80 z-10" />

        {/* Wavy Mask Divider SVG (fits left edge of right panel) */}
        <svg 
          className="absolute top-0 bottom-0 left-0 h-full w-24 text-[#13151a] fill-current pointer-events-none transform -translate-x-1/2 z-20" 
          viewBox="0 0 100 100" 
          preserveAspectRatio="none"
        >
          <path d="M100,0 C35,25 35,75 100,100 Z" />
        </svg>

        {/* Parallel Dotted Line Divider */}
        <svg 
          className="absolute top-0 bottom-0 left-0 h-full w-24 pointer-events-none transform -translate-x-[60%] z-20" 
          viewBox="0 0 100 100" 
          preserveAspectRatio="none"
        >
          <path d="M90,0 C25,25 25,75 90,100" fill="none" stroke="rgba(255, 255, 255, 0.15)" strokeWidth="0.5" strokeDasharray="4 4" />
        </svg>

        {/* Stylized geometric Logo Mark (.AW / .WO style) at bottom right */}
        <div className="relative z-20 flex items-center justify-center text-white/40 mb-2 mr-2">
          <svg className="w-16 h-12" fill="currentColor" viewBox="0 0 100 60">
            <circle cx="15" cy="50" r="4" />
            <path d="M28 50 L40 10 L46 10 L34 50 Z" />
            <path d="M42 50 L54 10 L60 10 L48 50 Z" />
            <path d="M56 50 L64 25 L70 25 L62 50 Z" />
            <circle cx="75" cy="25" r="3.5" />
          </svg>
        </div>

      </div>

    </div>
  )
}

export default function LoginPage() {
  return (
    <AuthProvider>
      <LoginForm />
    </AuthProvider>
  )
}



