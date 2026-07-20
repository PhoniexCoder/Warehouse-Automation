"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { User } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Spinner } from "@/components/ui/Spinner"

import { Modal } from "@/components/ui/Modal"

const roleColors: Record<string, string> = {
  SUPER_ADMIN: "bg-red-100 text-red-700",
  ADMIN: "bg-orange-100 text-orange-700",
  MANAGER: "bg-blue-100 text-blue-700",
  OPERATOR: "bg-green-100 text-green-700",
}

export default function UsersPage() {
  const { user, startImpersonation } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [impersonatingId, setImpersonatingId] = useState<string | null>(null)

  // Creation modal states
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState("OPERATOR")
  const [modalError, setModalError] = useState("")

  const isSuperAdmin = user?.role === "SUPER_ADMIN"

  const fetchUsers = useCallback(async () => {
    try {
      const data = await api.listUsers()
      setUsers(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  async function handleImpersonate(userId: string) {
    setImpersonatingId(userId)
    try {
      await startImpersonation(userId)
    } catch (err: any) {
      alert(err.response?.data?.error?.message || "Failed to impersonate user")
    } finally {
      setImpersonatingId(null)
    }
  }

  async function handleAddUser() {
    if (!username.trim() || !email.trim() || !password.trim()) return
    setSaving(true)
    setModalError("")
    try {
      await api.createUser({
        username,
        email,
        password,
        role,
      })
      setModalOpen(false)
      await fetchUsers()
    } catch (err: any) {
      setModalError(err.response?.data?.error?.message || err.message || "Failed to create user")
    } finally {
      setSaving(false)
    }
  }

  function openCreateModal() {
    setUsername("")
    setEmail("")
    setPassword("")
    setRole("OPERATOR")
    setModalError("")
    setModalOpen(true)
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Users</h1>
          <p className="text-sm text-slate-500 mt-1">{users.length} user{users.length !== 1 ? "s" : ""} registered</p>
        </div>
        <Button onClick={openCreateModal} className="flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add User
        </Button>
      </div>

      {users.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-slate-400">
            <p className="text-sm">No users found</p>
          </div>
        </Card>
      ) : (
        <Card padding={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/50">
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">User</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Email</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Role</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Status</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Joined</th>
                  <th className="text-right px-6 py-3 font-semibold text-slate-600">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-slate-50 hover:bg-slate-50/30 transition-colors">
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-blue-600 text-white rounded-full flex items-center justify-center text-xs font-bold shrink-0">
                          {u.username.charAt(0).toUpperCase()}
                        </div>
                        <span className="font-medium text-slate-900">{u.username}</span>
                      </div>
                    </td>
                    <td className="px-6 py-3 text-slate-500">{u.email}</td>
                    <td className="px-6 py-3">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${roleColors[u.role] || "bg-gray-100 text-gray-700"}`}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-6 py-3">
                      <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${u.is_active ? "text-green-600" : "text-red-500"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-green-500" : "bg-red-400"}`} />
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-slate-400 text-xs">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-3 text-right">
                      {isSuperAdmin && u.id !== user?.id && u.role !== "SUPER_ADMIN" && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleImpersonate(u.id)}
                          loading={impersonatingId === u.id}
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                          </svg>
                          Login as
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add User">
        <form onSubmit={(e) => { e.preventDefault(); handleAddUser() }} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input-field"
              placeholder="e.g. johndoe"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Email Address</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field"
              placeholder="e.g. johndoe@company.com"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              placeholder="Minimum 8 characters"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">User Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="input-field"
              required
            >
              {user?.role === "SUPER_ADMIN" && <option value="SUPER_ADMIN">SUPER_ADMIN</option>}
              {(user?.role === "SUPER_ADMIN" || user?.role === "ADMIN") && <option value="ADMIN">ADMIN</option>}
              {(user?.role === "SUPER_ADMIN" || user?.role === "ADMIN" || user?.role === "MANAGER") && <option value="MANAGER">MANAGER</option>}
              <option value="OPERATOR">OPERATOR</option>
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button type="submit" loading={saving}>Add User</Button>
          </div>
          {modalError && <p className="text-sm text-red-650 mt-2">{modalError}</p>}
        </form>
      </Modal>
    </div>
  )
}
