"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { Nvr, Warehouse } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Modal } from "@/components/ui/Modal"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"

export default function NvrsPage() {
  const { user } = useAuth()
  const [nvrs, setNvrs] = useState<Nvr[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Nvr | null>(null)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const [nvrName, setNvrName] = useState("")
  const [nvrIp, setNvrIp] = useState("")
  const [nvrPort, setNvrPort] = useState("34567")
  const [nvrProtocol, setNvrProtocol] = useState("dvrip")
  const [nvrUsername, setNvrUsername] = useState("")
  const [nvrPassword, setNvrPassword] = useState("")
  const [nvrWarehouseId, setNvrWarehouseId] = useState("")
  const [isTailscale, setIsTailscale] = useState(false)
  const [modalError, setModalError] = useState("")

  const [importModalOpen, setImportModalOpen] = useState(false)
  const [importNvr, setImportNvr] = useState<Nvr | null>(null)
  const [importChannels, setImportChannels] = useState<number[]>([])
  const [importing, setImporting] = useState(false)
  const [checkingIp, setCheckingIp] = useState(false)
  const [ipCheckResult, setIpCheckResult] = useState<{ reachable: boolean; has_dvrip: boolean; has_rtsp: boolean } | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [nvrList, whs] = await Promise.all([api.getNvrs(), api.getWarehouses()])
      setNvrs(nvrList)
      setWarehouses(whs)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  async function openCreate() {
    setEditing(null)
    setNvrName("")
    setNvrIp("")
    setNvrPort("34567")
    setNvrProtocol("dvrip")
    setNvrUsername("")
    setNvrPassword("")
    setNvrWarehouseId(warehouses[0]?.id || "")
    setIsTailscale(false)
    setModalError("")
    setModalOpen(true)
  }

  async function openEdit(nvr: Nvr) {
    setEditing(nvr)
    setNvrName(nvr.name)
    setNvrIp(nvr.ip_address)
    setNvrPort(String(nvr.port))
    setNvrProtocol(nvr.protocol)
    setNvrUsername("")
    setNvrPassword("")
    setNvrWarehouseId(nvr.warehouse_id)
    setIsTailscale(nvr.is_tailscale)
    setModalOpen(true)
  }

  async function handleSave() {
    if (!nvrName.trim() || !nvrIp.trim()) return
    setSaving(true)
    setModalError("")
    try {
      const payload: any = {
        name: nvrName,
        ip_address: nvrIp,
        port: parseInt(nvrPort) || 34567,
        protocol: nvrProtocol,
        is_tailscale: isTailscale,
      }
      if (nvrUsername) payload.username = nvrUsername
      if (nvrPassword) payload.password = nvrPassword

      if (editing) {
        await api.updateNvr(editing.id, payload)
      } else {
        payload.warehouse_id = nvrWarehouseId
        await api.createNvr(payload)
      }
      setModalOpen(false)
      await fetchData()
    } catch (err: any) {
      setModalError(err.response?.data?.error?.message || err.message || "Failed to save NVR")
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.deleteNvr(id)
      setConfirmDelete(null)
      await fetchData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to delete NVR")
      setConfirmDelete(null)
    }
  }

  async function handleCheckIp() {
    if (!nvrIp.trim()) return
    setCheckingIp(true)
    setIpCheckResult(null)
    try {
      const result = await api.checkNvrIp(nvrIp, parseInt(nvrPort) || 34567)
      setIpCheckResult(result)
    } catch {
      setIpCheckResult({ reachable: false, has_dvrip: false, has_rtsp: false })
    } finally {
      setCheckingIp(false)
    }
  }

  function openImport(nvr: Nvr) {
    setImportNvr(nvr)
    setImportChannels([])
    setImportModalOpen(true)
  }

  async function handleImport() {
    if (!importNvr || importChannels.length === 0) return
    setImporting(true)
    try {
      await api.importNvrChannels(importNvr.id, importChannels)
      setImportModalOpen(false)
      await fetchData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to import channels")
    } finally {
      setImporting(false)
    }
  }

  function toggleImportChannel(ch: number) {
    setImportChannels(prev =>
      prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch]
    )
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-foreground">NVRs</h2>
          <p className="text-sm text-secondary mt-1">Manage Network Video Recorders and import camera channels</p>
        </div>
        {user?.role !== "operator" && (
          <Button onClick={openCreate}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add NVR
          </Button>
        )}
      </div>

      {nvrs.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-secondary">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2" />
            </svg>
            <p className="font-medium">No NVRs configured</p>
            <p className="text-sm mt-1">Add an NVR to start importing camera channels</p>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {nvrs.map((nvr) => (
            <Card key={nvr.id} className="p-5 flex flex-col">
              <div className="flex items-start justify-between gap-2 mb-3">
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-foreground truncate">{nvr.name}</h3>
                  <p className="text-xs text-secondary mt-1 font-mono">{nvr.ip_address}:{nvr.port}</p>
                </div>
                <Badge variant={nvr.status === "active" ? "success" : "danger"}>
                  {nvr.status}
                </Badge>
              </div>

              <div className="space-y-1.5 text-xs text-secondary mb-4">
                <div className="flex items-center gap-2">
                  <span className="font-medium">Protocol:</span>
                  <span className="uppercase">{nvr.protocol}</span>
                </div>
                {nvr.is_tailscale && (
                  <div className="flex items-center gap-1.5 text-blue-600">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101" />
                    </svg>
                    <span>Tailscale</span>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <span className="font-medium">Cameras:</span>
                  <span>{nvr.camera_count ?? 0}</span>
                </div>
              </div>

              <div className="flex gap-2 mt-auto pt-3 border-t border-gray-100">
                <Button variant="secondary" size="sm" onClick={() => openImport(nvr)}>
                  Import Channels
                </Button>
                {user?.role !== "operator" && (
                  <>
                    <Button variant="secondary" size="sm" onClick={() => openEdit(nvr)}>Edit</Button>
                    <Button variant="danger" size="sm" onClick={() => setConfirmDelete(nvr.id)}>Delete</Button>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Create / Edit NVR Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? "Edit NVR" : "Add NVR"}>
        <form onSubmit={(e) => { e.preventDefault(); handleSave() }} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">NVR Name</label>
            <input
              value={nvrName}
              onChange={(e) => setNvrName(e.target.value)}
              className="input-field"
              placeholder="e.g. Main Building NVR"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">IP Address</label>
            <div className="flex gap-2">
              <input
                value={nvrIp}
                onChange={(e) => { setNvrIp(e.target.value); setIpCheckResult(null) }}
                className="input-field flex-1 font-mono"
                placeholder="192.168.1.35 or 100.64.0.5"
                required
              />
              <Button type="button" variant="secondary" onClick={handleCheckIp} loading={checkingIp} className="shrink-0">
                Check
              </Button>
            </div>
            {ipCheckResult && (
              <div className={`mt-2 text-xs p-2 rounded-lg ${ipCheckResult.reachable ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-700 border border-red-200"}`}>
                {ipCheckResult.reachable ? (
                  <>Reachable {ipCheckResult.has_dvrip && "• DVRIP"} {ipCheckResult.has_rtsp && "• RTSP"}</>
                ) : (
                  <>Not reachable — check IP, port, or Tailscale connection</>
                )}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Port</label>
              <input
                value={nvrPort}
                onChange={(e) => setNvrPort(e.target.value)}
                className="input-field font-mono"
                placeholder="34567"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Protocol</label>
              <select
                value={nvrProtocol}
                onChange={(e) => setNvrProtocol(e.target.value)}
                className="input-field"
              >
                <option value="dvrip">DVRIP</option>
                <option value="rtsp">RTSP</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Username</label>
              <input
                value={nvrUsername}
                onChange={(e) => setNvrUsername(e.target.value)}
                className="input-field"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
              <input
                type="password"
                value={nvrPassword}
                onChange={(e) => setNvrPassword(e.target.value)}
                className="input-field"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Warehouse</label>
            <select
              value={nvrWarehouseId}
              onChange={(e) => setNvrWarehouseId(e.target.value)}
              className="input-field"
              required
            >
              <option value="">Select warehouse</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isTailscale}
              onChange={(e) => setIsTailscale(e.target.checked)}
              className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4"
            />
            <span className="text-sm text-foreground">Tailscale IP (remote NVR)</span>
          </label>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button type="submit" loading={saving}>{editing ? "Save Changes" : "Add NVR"}</Button>
          </div>
          {modalError && <p className="text-sm text-red-600 mt-2">{modalError}</p>}
        </form>
      </Modal>

      {/* Import Channels Modal */}
      <Modal open={importModalOpen} onClose={() => setImportModalOpen(false)} title={`Import Channels — ${importNvr?.name || ""}`}>
        <div className="space-y-4">
          <p className="text-sm text-secondary">
            Select channels (0–15) to import as cameras. Each channel will be linked to this NVR.
          </p>
          <div className="grid grid-cols-4 gap-2 max-h-60 overflow-y-auto border border-slate-200 rounded-lg p-3 bg-slate-50/50">
            {Array.from({ length: 16 }, (_, i) => (
              <label key={i} className="flex items-center gap-2 p-2 bg-white rounded border border-slate-200/60 cursor-pointer hover:bg-slate-50 transition-colors">
                <input
                  type="checkbox"
                  checked={importChannels.includes(i)}
                  onChange={() => toggleImportChannel(i)}
                  className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4"
                />
                <span className="text-xs font-medium text-slate-700">Ch {i}</span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setImportModalOpen(false)}>Cancel</Button>
            <Button onClick={handleImport} loading={importing} disabled={importChannels.length === 0}>
              Import Selected ({importChannels.length})
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete NVR" size="sm">
        <p className="text-sm text-secondary">
          Are you sure you want to delete this NVR? All linked cameras will be unlinked but not deleted.
        </p>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => confirmDelete && handleDelete(confirmDelete)}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
