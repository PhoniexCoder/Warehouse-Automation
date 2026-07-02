"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import type { Camera, Warehouse } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Modal } from "@/components/ui/Modal"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"

export default function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Camera | null>(null)
  const [cameraName, setCameraName] = useState("")
  const [streamUrl, setStreamUrl] = useState("")
  const [warehouseId, setWarehouseId] = useState("")
  const [cameraStatus, setCameraStatus] = useState("online")
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>("all")

  const fetch = useCallback(async () => {
    try {
      const [cams, whs] = await Promise.all([
        api.getCameras(),
        api.getWarehouses(),
      ])
      setCameras(cams)
      setWarehouses(whs)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetch() }, [fetch])

  function openCreate() {
    setEditing(null)
    setCameraName("")
    setStreamUrl("")
    setWarehouseId(warehouses[0]?.id || "")
    setCameraStatus("online")
    setModalOpen(true)
  }

  function openEdit(c: Camera) {
    setEditing(c)
    setCameraName(c.camera_name)
    setStreamUrl(c.stream_url || "")
    setWarehouseId(c.warehouse_id)
    setCameraStatus(c.status)
    setModalOpen(true)
  }

  async function handleSave() {
    if (!cameraName.trim()) return
    setSaving(true)
    try {
      if (editing) {
        await api.updateCamera(editing.id, {
          camera_name: cameraName,
          stream_url: streamUrl,
          status: cameraStatus,
        })
      } else {
        await api.createCamera({
          warehouse_id: warehouseId,
          camera_name: cameraName,
          stream_url: streamUrl,
          status: cameraStatus,
        })
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
    await api.deleteCamera(id)
    setConfirmDelete(null)
    await fetch()
  }

  const filtered = cameras.filter((c) => {
    if (statusFilter === "all") return true
    return c.status === statusFilter
  })

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Cameras</h2>
          <p className="text-sm text-secondary mt-1">Manage surveillance cameras</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="input-field w-auto"
          >
            <option value="all">All Status</option>
            <option value="online">Online</option>
            <option value="offline">Offline</option>
          </select>
          <Button onClick={openCreate}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Camera
          </Button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-secondary">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <p className="font-medium">No cameras found</p>
            <p className="text-sm mt-1">Add a camera to start monitoring</p>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((c) => (
            <Card key={c.id}>
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${c.status === "online" ? "bg-success" : "bg-danger"}`} />
                    <h3 className="font-semibold text-foreground truncate">{c.camera_name}</h3>
                  </div>
                  {c.stream_url && (
                    <p className="text-xs text-secondary mt-1.5 truncate font-mono">{c.stream_url}</p>
                  )}
                  <p className="text-xs text-secondary mt-1.5">
                    {c.last_seen ? (
                      <>Last seen {format(new Date(c.last_seen), "MMM d, HH:mm")}</>
                    ) : (
                      "No activity yet"
                    )}
                  </p>
                </div>
                <Badge variant={c.status === "online" ? "success" : "danger"}>
                  {c.status}
                </Badge>
              </div>
              <div className="flex gap-2 mt-4 pt-3 border-t border-gray-100">
                <Button variant="secondary" size="sm" onClick={() => openEdit(c)}>Edit</Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    await api.updateCamera(c.id, {
                      status: c.status === "online" ? "offline" : "online",
                    })
                    await fetch()
                  }}
                >
                  {c.status === "online" ? "Set Offline" : "Set Online"}
                </Button>
                <Button variant="danger" size="sm" onClick={() => setConfirmDelete(c.id)}>Delete</Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? "Edit Camera" : "Add Camera"}>
        <form onSubmit={(e) => { e.preventDefault(); handleSave() }} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Camera Name</label>
            <input
              value={cameraName}
              onChange={(e) => setCameraName(e.target.value)}
              className="input-field"
              placeholder="e.g. Loading Dock North"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Stream URL</label>
            <input
              value={streamUrl}
              onChange={(e) => setStreamUrl(e.target.value)}
              className="input-field font-mono text-xs"
              placeholder="rtsp://192.168.1.100:554/stream"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Warehouse</label>
            <select
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
              className="input-field"
              required
            >
              <option value="">Select warehouse</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </div>
          {editing && (
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Status</label>
              <select
                value={cameraStatus}
                onChange={(e) => setCameraStatus(e.target.value)}
                className="input-field"
              >
                <option value="online">Online</option>
                <option value="offline">Offline</option>
              </select>
            </div>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button type="submit" loading={saving}>{editing ? "Save Changes" : "Add Camera"}</Button>
          </div>
        </form>
      </Modal>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete Camera" size="sm">
        <p className="text-sm text-secondary">Are you sure you want to delete this camera?</p>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => confirmDelete && handleDelete(confirmDelete)}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
