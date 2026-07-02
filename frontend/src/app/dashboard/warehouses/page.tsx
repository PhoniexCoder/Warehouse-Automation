"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import type { Warehouse } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Modal } from "@/components/ui/Modal"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"

export default function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Warehouse | null>(null)
  const [name, setName] = useState("")
  const [location, setLocation] = useState("")
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    try {
      const data = await api.getWarehouses()
      setWarehouses(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetch() }, [fetch])

  function openCreate() {
    setEditing(null)
    setName("")
    setLocation("")
    setModalOpen(true)
  }

  function openEdit(w: Warehouse) {
    setEditing(w)
    setName(w.name)
    setLocation(w.location)
    setModalOpen(true)
  }

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    try {
      if (editing) {
        await api.deleteWarehouse(editing.id)
        await api.createWarehouse({ name, location })
      } else {
        await api.createWarehouse({ name, location })
      }
      setModalOpen(false)
      await fetch()
    } catch {
      // silent
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    await api.deleteWarehouse(id)
    setConfirmDelete(null)
    await fetch()
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Warehouses</h2>
          <p className="text-sm text-secondary mt-1">Manage warehouse locations</p>
        </div>
        <Button onClick={openCreate}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Warehouse
        </Button>
      </div>

      {warehouses.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-secondary">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
            <p className="font-medium">No warehouses yet</p>
            <p className="text-sm mt-1">Create your first warehouse to get started</p>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {warehouses.map((w) => (
            <Card key={w.id}>
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-foreground truncate">{w.name}</h3>
                  {w.location && (
                    <p className="text-sm text-secondary mt-1 flex items-center gap-1.5">
                      <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                      {w.location}
                    </p>
                  )}
                  <p className="text-xs text-secondary mt-2">
                    Created {format(new Date(w.created_at), "MMM d, yyyy")}
                  </p>
                </div>
              </div>
              <div className="flex gap-2 mt-4 pt-3 border-t border-gray-100">
                <Button variant="secondary" size="sm" onClick={() => openEdit(w)}>
                  Edit
                </Button>
                <Button variant="danger" size="sm" onClick={() => setConfirmDelete(w.id)}>
                  Delete
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? "Edit Warehouse" : "Add Warehouse"}>
        <form onSubmit={(e) => { e.preventDefault(); handleSave() }} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Warehouse Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input-field"
              placeholder="e.g. Main Distribution Center"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Location</label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="input-field"
              placeholder="e.g. 123 Industrial Blvd, Detroit, MI"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button type="submit" loading={saving}>
              {editing ? "Save Changes" : "Create Warehouse"}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete Warehouse" size="sm">
        <p className="text-sm text-secondary">Are you sure you want to delete this warehouse? This action cannot be undone.</p>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => confirmDelete && handleDelete(confirmDelete)}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
