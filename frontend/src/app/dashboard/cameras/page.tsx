"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { Camera, Warehouse, Nvr } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Modal } from "@/components/ui/Modal"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"
import { RoiOverlay } from "@/components/camera/RoiOverlay"

const getMjpegUrl = (id: string): string => {
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname
    return `http://${hostname}:8000/api/v1/stream/${id}`
  }
  return `http://localhost:8000/api/v1/stream/${id}`
}

export default function CamerasPage() {
  const { user } = useAuth()
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

  // DVRIP connect state
  const [dvripModalOpen, setDvripModalOpen] = useState(false)
  const [dvripHost, setDvripHost] = useState("")
  const [dvripUsername, setDvripUsername] = useState("")
  const [dvripPassword, setDvripPassword] = useState("")
  const [dvripConnecting, setDvripConnecting] = useState(false)

  // go2rtc channel state
  const [go2rtcChannels, setGo2rtcChannels] = useState<Record<string, string>>({})
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null)

  // VMS discovery state
  const [discoverModalOpen, setDiscoverModalOpen] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [discoveredDevices, setDiscoveredDevices] = useState<any[]>([])
  const [selectedDeviceIp, setSelectedDeviceIp] = useState("")
  const [manualIp, setManualIp] = useState("")
  const [nvrUsername, setNvrUsername] = useState("")
  const [nvrPassword, setNvrPassword] = useState("")
  const [scanningChannels, setScanningChannels] = useState(false)
  const [scannedChannels, setScannedChannels] = useState<any[]>([])
  const [selectedChannels, setSelectedChannels] = useState<number[]>([])
  const [importing, setImporting] = useState(false)

  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [models, setModels] = useState<{ path: string; name: string; size_bytes: number }[]>([])
  const [roi, setRoi] = useState<{ x: number; y: number }[] | null>(null)
  const [roiDrawing, setRoiDrawing] = useState(false)
  const [nvrs, setNvrs] = useState<Nvr[]>([])
  const [modalError, setModalError] = useState("")

  // Consolidated NVR Tab & Modal States
  const [activeTab, setActiveTab] = useState<"cameras" | "nvrs">("cameras")
  const [nvrModalOpen, setNvrModalOpen] = useState(false)
  const [editingNvr, setEditingNvr] = useState<Nvr | null>(null)
  const [savingNvr, setSavingNvr] = useState(false)
  const [confirmDeleteNvr, setConfirmDeleteNvr] = useState<string | null>(null)

  const [formNvrName, setFormNvrName] = useState("")
  const [formNvrIp, setFormNvrIp] = useState("")
  const [formNvrPort, setFormNvrPort] = useState("34567")
  const [formNvrProtocol, setFormNvrProtocol] = useState("dvrip")
  const [formNvrUsername, setFormNvrUsername] = useState("")
  const [formNvrPassword, setFormNvrPassword] = useState("")
  const [formNvrWarehouseId, setFormNvrWarehouseId] = useState("")
  const [formNvrIsTailscale, setFormNvrIsTailscale] = useState(false)
  const [nvrModalError, setNvrModalError] = useState("")

  const [nvrImportModalOpen, setNvrImportModalOpen] = useState(false)
  const [nvrImportNvr, setNvrImportNvr] = useState<Nvr | null>(null)
  const [nvrImportChannels, setNvrImportChannels] = useState<number[]>([])
  const [nvrImporting, setNvrImporting] = useState(false)
  const [nvrCheckingIp, setNvrCheckingIp] = useState(false)
  const [nvrIpCheckResult, setNvrIpCheckResult] = useState<{ reachable: boolean; has_dvrip: boolean; has_rtsp: boolean } | null>(null)

  async function openCreateNvr() {
    setEditingNvr(null)
    setFormNvrName("")
    setFormNvrIp("")
    setFormNvrPort("34567")
    setFormNvrProtocol("dvrip")
    setFormNvrUsername("")
    setFormNvrPassword("")
    setFormNvrWarehouseId(warehouses[0]?.id || "")
    setFormNvrIsTailscale(false)
    setNvrModalError("")
    setNvrModalOpen(true)
  }

  async function openEditNvr(nvr: Nvr) {
    setEditingNvr(nvr)
    setFormNvrName(nvr.name)
    setFormNvrIp(nvr.ip_address)
    setFormNvrPort(String(nvr.port))
    setFormNvrProtocol(nvr.protocol)
    setFormNvrUsername("")
    setFormNvrPassword("")
    setFormNvrWarehouseId(nvr.warehouse_id)
    setFormNvrIsTailscale(nvr.is_tailscale)
    setNvrModalOpen(true)
  }

  async function handleSaveNvr() {
    if (!formNvrName.trim() || !formNvrIp.trim()) return
    setSavingNvr(true)
    setNvrModalError("")
    try {
      const payload: any = {
        name: formNvrName,
        ip_address: formNvrIp,
        port: parseInt(formNvrPort) || 34567,
        protocol: formNvrProtocol,
        is_tailscale: formNvrIsTailscale,
      }
      if (formNvrUsername) payload.username = formNvrUsername
      if (formNvrPassword) payload.password = formNvrPassword

      if (editingNvr) {
        await api.updateNvr(editingNvr.id, payload)
      } else {
        payload.warehouse_id = formNvrWarehouseId
        await api.createNvr(payload)
      }
      setNvrModalOpen(false)
      await fetchCamerasData()
    } catch (err: any) {
      setNvrModalError(err.response?.data?.error?.message || err.message || "Failed to save NVR")
    } finally {
      setSavingNvr(false)
    }
  }

  async function handleDeleteNvr(id: string) {
    try {
      await api.deleteNvr(id)
      setConfirmDeleteNvr(null)
      await fetchCamerasData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to delete NVR")
      setConfirmDeleteNvr(null)
    }
  }

  async function handleCheckNvrIp() {
    if (!formNvrIp.trim()) return
    setNvrCheckingIp(true)
    setNvrIpCheckResult(null)
    try {
      const result = await api.checkNvrIp(formNvrIp, parseInt(formNvrPort) || 34567)
      setNvrIpCheckResult(result)
    } catch {
      setNvrIpCheckResult({ reachable: false, has_dvrip: false, has_rtsp: false })
    } finally {
      setNvrCheckingIp(false)
    }
  }

  function openImportNvrChannels(nvr: Nvr) {
    setNvrImportNvr(nvr)
    setNvrImportChannels([])
    setNvrImportModalOpen(true)
  }

  async function handleImportNvrChannels() {
    if (!nvrImportNvr || nvrImportChannels.length === 0) return
    setNvrImporting(true)
    try {
      await api.importNvrChannels(nvrImportNvr.id, nvrImportChannels)
      setNvrImportModalOpen(false)
      await fetchCamerasData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to import channels")
    } finally {
      setNvrImporting(false)
    }
  }

  function toggleNvrImportChannel(ch: number) {
    setNvrImportChannels(prev =>
      prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch]
    )
  }

  const fetchCamerasData = useCallback(async () => {
    try {
      const [cams, whs, nvrList] = await Promise.all([
        api.getCameras(),
        api.getWarehouses(),
        api.getNvrs(),
      ])
      setCameras(cams)
      setWarehouses(whs)
      setNvrs(nvrList)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchCamerasData() }, [fetchCamerasData])

  async function openCreate() {
    setEditing(null)
    setCameraName("")
    setStreamUrl("")
    setWarehouseId(warehouses[0]?.id || "")
    setCameraStatus("online")
    setSelectedChannel(null)
    setSelectedModel(null)
    setRoi(null)
    setRoiDrawing(false)
    setModalError("")
    setModalOpen(true)
    try {
      const [streams, modelsList] = await Promise.all([
        api.getGo2rtcStreams(),
        api.getModels(),
      ])
      setGo2rtcChannels(streams)
      setModels(modelsList)
    } catch {
      setGo2rtcChannels({})
    }
  }

  async function openEdit(c: Camera) {
    setEditing(c)
    setCameraName(c.camera_name)
    setStreamUrl(c.stream_url || "")
    setWarehouseId(c.warehouse_id)
    setCameraStatus(c.status)
    setSelectedChannel(null)
    setSelectedModel(c.model_path || null)
    setRoi(c.roi || null)
    setRoiDrawing(false)
    setModalOpen(true)
    try {
      const [streams, modelsList] = await Promise.all([
        api.getGo2rtcStreams(),
        api.getModels(),
      ])
      setGo2rtcChannels(streams)
      setModels(modelsList)
      const match = c.stream_url?.match(/rtsp:\/\/go2rtc:8554\/(\w+)/)
      if (match && streams[match[1]]) {
        setSelectedChannel(match[1])
      }
    } catch {
      setGo2rtcChannels({})
    }
  }

  async function handleSave() {
    if (!cameraName.trim()) return
    setSaving(true)
    setModalError("")
    try {
      if (editing) {
        await api.updateCamera(editing.id, {
          camera_name: cameraName,
          stream_url: streamUrl,
          status: cameraStatus,
          model_path: selectedModel,
          roi: roi,
        })
      } else {
        await api.createCamera({
          warehouse_id: warehouseId,
          camera_name: cameraName,
          stream_url: streamUrl,
          status: cameraStatus,
          model_path: selectedModel,
          roi: roi,
        })
      }
      setModalOpen(false)
      await fetchCamerasData()
    } catch (err: any) {
      setModalError(err.response?.data?.error?.message || err.message || "Failed to save camera")
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.deleteCamera(id)
      setConfirmDelete(null)
      await fetchCamerasData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to delete camera")
      setConfirmDelete(null)
    }
  }

  async function openDiscover() {
    setDiscoverModalOpen(true)
    setDiscovering(true)
    setSelectedDeviceIp("")
    setManualIp("")
    setScannedChannels([])
    setSelectedChannels([])
    try {
      const devices = await api.discoverVms()
      setDiscoveredDevices(devices)
      if (devices.length > 0) {
        setSelectedDeviceIp(devices[0].ip)
      }
    } catch {
      // silent
    } finally {
      setDiscovering(false)
    }
  }

  async function handleScanChannels() {
    const targetIp = selectedDeviceIp || manualIp
    if (!targetIp) return
    setScanningChannels(true)
    try {
      const chs = await api.scanVmsChannels({
        ip: targetIp,
        username: nvrUsername,
        password: nvrPassword
      })
      setScannedChannels(chs)
      setSelectedChannels(chs.map((c: any) => c.channel_id))
    } catch {
      // silent
    } finally {
      setScanningChannels(false)
    }
  }

  async function handleImport() {
    const targetIp = selectedDeviceIp || manualIp
    if (!targetIp || selectedChannels.length === 0) return
    setImporting(true)
    try {
      await api.importVmsCameras({
        warehouse_id: warehouseId || warehouses[0]?.id,
        ip: targetIp,
        username: nvrUsername,
        password: nvrPassword,
        channels: selectedChannels
      })
      setDiscoverModalOpen(false)
      await fetchCamerasData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to import cameras")
    } finally {
      setImporting(false)
    }
  }

  function toggleChannel(chId: number) {
    setSelectedChannels(prev =>
      prev.includes(chId) ? prev.filter(id => id !== chId) : [...prev, chId]
    )
  }

  async function handleDvripConnect() {
    if (!dvripHost.trim()) return
    setDvripConnecting(true)
    try {
      const result = await api.dvripConnect({
        warehouse_id: warehouseId || warehouses[0]?.id,
        host: dvripHost,
        username: dvripUsername,
        password: dvripPassword,
      })
      setDvripModalOpen(false)
      await fetchCamerasData()
    } catch (err: any) {
      alert(err.response?.data?.error?.message || err.message || "Failed to connect via DVRIP")
    } finally {
      setDvripConnecting(false)
    }
  }

  function getNvrName(nvrId: string | null): string | null {
    if (!nvrId) return null
    const nvr = nvrs.find(n => n.id === nvrId)
    return nvr?.name || null
  }

  const filtered = cameras.filter((c) => {
    if (c.status === "active" || c.status === "online") {
      const hStatus = c.health?.status
      if (hStatus === "reconnecting" || hStatus === "dead" || hStatus === "error") {
        return false
      }
    }
    if (statusFilter === "all") return true
    return c.status === statusFilter
  })

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Cameras &amp; NVRs</h2>
          <p className="text-sm text-secondary mt-1">
            {activeTab === "cameras"
              ? "Manage surveillance cameras and monitor live feeds"
              : "Manage Network Video Recorders and import channels"
            }
          </p>
        </div>
        <div className="flex items-center gap-3">
          {activeTab === "cameras" ? (
            <>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="input-field w-auto"
              >
                <option value="all">All Status</option>
                <option value="online">Online</option>
                <option value="offline">Offline</option>
              </select>
              {user?.role !== "operator" && (
                <>
                  <Button onClick={openDiscover} variant="secondary" className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    Auto-Discover
                  </Button>
                  <Button onClick={() => setDvripModalOpen(true)} variant="secondary" className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    DVRIP Connect
                  </Button>
                  <Button onClick={openCreate}>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    Add Camera
                  </Button>
                </>
              )}
            </>
          ) : (
            user?.role !== "operator" && (
              <Button onClick={openCreateNvr}>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add NVR
              </Button>
            )
          )}
        </div>
      </div>

      {/* Sleek Tab Bar Selector */}
      <div className="flex border-b border-slate-200">
        <button
          onClick={() => setActiveTab("cameras")}
          className={`px-5 py-3 text-xs font-bold uppercase tracking-wider transition-colors border-b-2 -mb-[2px] ${
            activeTab === "cameras"
              ? "border-orange-500 text-slate-900 font-extrabold"
              : "border-transparent text-slate-400 hover:text-slate-755 hover:border-slate-300"
          }`}
        >
          Live Camera Feeds
        </button>
        <button
          onClick={() => setActiveTab("nvrs")}
          className={`px-5 py-3 text-xs font-bold uppercase tracking-wider transition-colors border-b-2 -mb-[2px] ${
            activeTab === "nvrs"
              ? "border-orange-500 text-slate-900 font-extrabold"
              : "border-transparent text-slate-400 hover:text-slate-755 hover:border-slate-300"
          }`}
        >
          Network Video Recorders (NVR)
        </button>
      </div>

      {/* Cameras View */}
      {activeTab === "cameras" && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-bold text-foreground">Managed Cameras</h3>
              <p className="text-xs text-secondary mt-0.5">CRUD management for surveillance cameras</p>
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
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {filtered.map((c) => (
                <Card key={c.id} className="overflow-hidden p-0 flex flex-col h-full bg-white border border-slate-200/60 rounded-2xl shadow-sm">
                  <div className="relative bg-black aspect-video overflow-hidden w-full">
                    {c.status === "active" || c.status === "online" ? (
                      <img
                        src={getMjpegUrl(c.id)}
                        alt={`${c.camera_name} live stream`}
                        className="w-full h-full object-contain"
                      />
                    ) : (
                      <div className="flex flex-col items-center justify-center h-full text-slate-600">
                        <svg className="w-10 h-10 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                        <span className="text-xs uppercase tracking-wider font-mono">
                          offline
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="p-4 flex-1 flex flex-col justify-between">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${c.status === "active" || c.status === "online" ? "bg-success" : "bg-danger"}`} />
                          <h3 className="font-semibold text-foreground truncate">{c.camera_name}</h3>
                        </div>
                        {c.stream_url && (
                          <p className="text-xs text-secondary mt-1.5 truncate font-mono">{c.stream_url}</p>
                        )}
                        <div className="flex items-center gap-2 mt-1.5">
                          {c.nvr_id && (() => {
                            const name = getNvrName(c.nvr_id)
                            return name ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-50 text-purple-600 font-medium">
                                {name}
                              </span>
                            ) : null
                          })()}
                          {c.model_path && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-medium">
                              {c.model_path.split("/").pop()?.replace(".pt", "")}
                            </span>
                          )}
                          {c.roi && c.roi.length > 0 && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-50 text-green-600 font-medium">
                              ROI
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-secondary mt-1.5">
                          {c.last_seen ? (
                            <>Last seen {format(new Date(c.last_seen), "MMM d, HH:mm")}</>
                          ) : (
                            "No activity yet"
                          )}
                        </p>
                      </div>
                      <Badge variant={c.status === "active" || c.status === "online" ? "success" : "danger"}>
                        {c.status}
                      </Badge>
                    </div>

                    {user?.role !== "operator" && (
                      <div className="flex gap-2 mt-4 pt-3 border-t border-gray-100">
                        <Button variant="secondary" size="sm" onClick={() => openEdit(c)}>Edit</Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={async () => {
                            const nextStatus = (c.status === "active" || c.status === "online") ? "offline" : "active"
                            await api.updateCamera(c.id, {
                              status: nextStatus,
                            })
                            await fetchCamerasData()
                          }}
                        >
                          {(c.status === "active" || c.status === "online") ? "Set Offline" : "Set Online"}
                        </Button>
                        <Button variant="danger" size="sm" onClick={() => setConfirmDelete(c.id)}>Delete</Button>
                      </div>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </section>
      )}

      {/* NVRs View */}
      {activeTab === "nvrs" && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-bold text-foreground">Managed NVRs</h3>
              <p className="text-xs text-secondary mt-0.5">Configure hardware Network Video Recorders</p>
            </div>
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
                <Card key={nvr.id} className="p-5 flex flex-col bg-white border border-slate-200/60 rounded-2xl shadow-sm">
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
                    <Button variant="secondary" size="sm" onClick={() => openImportNvrChannels(nvr)}>
                      Import Channels
                    </Button>
                    {user?.role !== "operator" && (
                      <>
                        <Button variant="secondary" size="sm" onClick={() => openEditNvr(nvr)}>Edit</Button>
                        <Button variant="danger" size="sm" onClick={() => setConfirmDeleteNvr(nvr.id)}>Delete</Button>
                      </>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </section>
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
          {Object.keys(go2rtcChannels).length > 0 && (
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">go2rtc Channel</label>
              <select
                value={selectedChannel || ""}
                onChange={(e) => {
                  const key = e.target.value || null
                  setSelectedChannel(key)
                  if (key) {
                    setCameraName(key)
                    setStreamUrl(`rtsp://go2rtc:8554/${key}`)
                  }
                }}
                className="input-field"
              >
                <option value="">Custom URL</option>
                {Object.keys(go2rtcChannels).map((key) => (
                  <option key={key} value={key}>{key}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Stream URL</label>
            <input
              value={streamUrl}
              onChange={(e) => {
                setStreamUrl(e.target.value)
                const match = e.target.value.match(/rtsp:\/\/go2rtc:8554\/(\w+)/)
                if (match && go2rtcChannels[match[1]]) {
                  setSelectedChannel(match[1])
                } else {
                  setSelectedChannel(null)
                }
              }}
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

          <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">ML Model</label>
              <select
                value={selectedModel || ""}
                onChange={(e) => setSelectedModel(e.target.value || null)}
                className="input-field"
              >
                <option value="">No model (stream only)</option>
                {models.map((m) => (
                  <option key={m.path} value={m.path}>{m.name}</option>
                ))}
              </select>
              {models.length === 0 && (
                <p className="text-xs text-amber-600 mt-1">No .pt files found in models/ directory</p>
              )}
            </div>

          {editing && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-sm font-medium text-foreground">Region of Interest (ROI)</label>
                <div className="flex items-center gap-2">
                  {roi && roi.length > 0 && (
                    <button
                      type="button"
                      onClick={() => { setRoi(null); setRoiDrawing(false) }}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Clear ROI
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setRoiDrawing(!roiDrawing)}
                    className={`text-xs px-2 py-0.5 rounded ${roiDrawing ? "bg-green-100 text-green-700 border border-green-300" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                  >
                    {roiDrawing ? "Drawing..." : "Draw ROI"}
                  </button>
                </div>
              </div>
              <p className="text-xs text-secondary mb-2">
                {roiDrawing
                  ? "Click to add points, double-click to finish. Detection will be limited to the ROI area."
                  : roi && roi.length > 2
                    ? `${roi.length} points defined — detection limited to ROI area`
                    : "No ROI set — detection runs on full frame"
                }
              </p>
              {(editing.stream_url || editing.id) && (
                <div className="relative bg-black rounded-lg overflow-hidden" style={{ aspectRatio: "16/9" }}>
                  <RoiOverlay
                    mjpegUrl={getMjpegUrl(editing.id)}
                    roi={roi}
                    onRoiChange={(newRoi) => setRoi(newRoi)}
                    onDrawingComplete={() => setRoiDrawing(false)}
                    drawing={roiDrawing}
                  />
                </div>
              )}
            </div>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button type="submit" loading={saving}>{editing ? "Save Changes" : "Add Camera"}</Button>
          </div>
          {modalError && <p className="text-sm text-red-600 mt-2">{modalError}</p>}
        </form>
      </Modal>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete Camera" size="sm">
        <p className="text-sm text-secondary">Are you sure you want to delete this camera?</p>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => confirmDelete && handleDelete(confirmDelete)}>Delete</Button>
        </div>
      </Modal>

      <Modal open={discoverModalOpen} onClose={() => setDiscoverModalOpen(false)} title="VMS Auto-Discovery">
        <div className="space-y-4 select-text">
          {discovering ? (
            <div className="flex flex-col items-center justify-center py-8 space-y-3">
              <Spinner className="w-8 h-8" />
              <p className="text-sm text-secondary">Searching local network interface subnet for active NVRs and cameras...</p>
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">Select Discovered NVR / IP Camera</label>
                {discoveredDevices.length === 0 ? (
                  <div className="text-xs text-secondary bg-slate-50 border border-slate-200 rounded-lg p-3.5 mb-2">
                    No cameras auto-detected on standard ONVIF multicast discovery.
                  </div>
                ) : (
                  <select
                    value={selectedDeviceIp}
                    onChange={(e) => {
                      setSelectedDeviceIp(e.target.value)
                      setManualIp("")
                    }}
                    className="input-field mb-2"
                  >
                    {discoveredDevices.map((d) => (
                      <option key={d.ip} value={d.ip}>{d.name}</option>
                    ))}
                  </select>
                )}
                <div className="mt-2.5">
                  <label className="block text-xs text-secondary mb-1">Or enter NVR IP Address manually:</label>
                  <input
                    value={manualIp}
                    onChange={(e) => {
                      setManualIp(e.target.value)
                      setSelectedDeviceIp("")
                    }}
                    placeholder="e.g. 192.168.1.35"
                    className="input-field text-xs font-mono"
                  />
                </div>
              </div>

              {(selectedDeviceIp || manualIp) && (
                <div className="border-t border-slate-100 pt-4 space-y-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-foreground mb-1.5">NVR Username</label>
                      <input
                        value={nvrUsername}
                        onChange={(e) => setNvrUsername(e.target.value)}
                        className="input-field"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-foreground mb-1.5">NVR Password</label>
                      <input
                        type="password"
                        value={nvrPassword}
                        onChange={(e) => setNvrPassword(e.target.value)}
                        className="input-field"
                      />
                    </div>
                  </div>

                  <Button onClick={handleScanChannels} loading={scanningChannels} className="w-full">
                    Scan Active NVR Channels
                  </Button>
                </div>
              )}

              {scannedChannels.length > 0 && (
                <div className="border-t border-slate-100 pt-4 space-y-4">
                  <div>
                    <h4 className="text-sm font-bold text-foreground mb-2">Active Channels Found</h4>
                    <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto border border-slate-200 rounded-lg p-2 bg-slate-50/50">
                      {scannedChannels.map((c) => (
                        <label key={c.channel_id} className="flex items-center gap-2.5 p-2 bg-white rounded border border-slate-200/60 cursor-pointer hover:bg-slate-50 transition-colors">
                          <input
                            type="checkbox"
                            checked={selectedChannels.includes(c.channel_id)}
                            onChange={() => toggleChannel(c.channel_id)}
                            className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4"
                          />
                          <div className="text-xs">
                            <p className="font-semibold text-slate-800">Channel {c.channel_id}</p>
                            <p className="text-[10px] text-emerald-500 font-medium">Signal detected</p>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1.5">Target Warehouse</label>
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

                  <div className="flex justify-end gap-3 pt-2">
                    <Button variant="secondary" onClick={() => setDiscoverModalOpen(false)}>Cancel</Button>
                    <Button onClick={handleImport} loading={importing} disabled={selectedChannels.length === 0}>
                      Import Selected Channels ({selectedChannels.length})
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </Modal>

      <Modal open={dvripModalOpen} onClose={() => setDvripModalOpen(false)} title="DVRIP Quick Connect">
        <div className="space-y-4">
          <p className="text-sm text-secondary">
            Connect to a TVS/XM NVR via native DVRIP protocol. All 16 channels will be auto-imported and streaming will start automatically.
          </p>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">NVR IP Address</label>
            <input
              value={dvripHost}
              onChange={(e) => setDvripHost(e.target.value)}
              className="input-field font-mono"
              placeholder="192.168.1.35"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Username</label>
              <input
                value={dvripUsername}
                onChange={(e) => setDvripUsername(e.target.value)}
                className="input-field"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
              <input
                type="password"
                value={dvripPassword}
                onChange={(e) => setDvripPassword(e.target.value)}
                className="input-field"
              />
            </div>
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
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
            <p className="text-xs text-blue-700">
              <strong>Protocol:</strong> Native DVRIP (TCP port 34567) — no RTSP or FFmpeg required.
              Connects directly to the NVR for lower latency and more reliable streaming.
            </p>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setDvripModalOpen(false)}>Cancel</Button>
            <Button onClick={handleDvripConnect} loading={dvripConnecting} className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Connect &amp; Stream All Channels
            </Button>
          </div>
        </div>
      </Modal>

      {/* Create / Edit NVR Modal */}
      <Modal open={nvrModalOpen} onClose={() => setNvrModalOpen(false)} title={editingNvr ? "Edit NVR" : "Add NVR"}>
        <form onSubmit={(e) => { e.preventDefault(); handleSaveNvr() }} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">NVR Name</label>
            <input
              value={formNvrName}
              onChange={(e) => setFormNvrName(e.target.value)}
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
                value={formNvrIp}
                onChange={(e) => { setFormNvrIp(e.target.value); setNvrIpCheckResult(null) }}
                className="input-field flex-1 font-mono"
                placeholder="192.168.1.35 or 100.64.0.5"
                required
              />
              <Button type="button" variant="secondary" onClick={handleCheckNvrIp} loading={nvrCheckingIp} className="shrink-0">
                Check
              </Button>
            </div>
            {nvrIpCheckResult && (
              <div className={`mt-2 text-xs p-2 rounded-lg ${nvrIpCheckResult.reachable ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-700 border border-red-200"}`}>
                {nvrIpCheckResult.reachable ? (
                  <>Reachable {nvrIpCheckResult.has_dvrip && "• DVRIP"} {nvrIpCheckResult.has_rtsp && "• RTSP"}</>
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
                value={formNvrPort}
                onChange={(e) => setFormNvrPort(e.target.value)}
                className="input-field font-mono"
                placeholder="34567"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Protocol</label>
              <select
                value={formNvrProtocol}
                onChange={(e) => setFormNvrProtocol(e.target.value)}
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
                value={formNvrUsername}
                onChange={(e) => setFormNvrUsername(e.target.value)}
                className="input-field"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
              <input
                type="password"
                value={formNvrPassword}
                onChange={(e) => setFormNvrPassword(e.target.value)}
                className="input-field"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Warehouse</label>
            <select
              value={formNvrWarehouseId}
              onChange={(e) => setFormNvrWarehouseId(e.target.value)}
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
              checked={formNvrIsTailscale}
              onChange={(e) => setFormNvrIsTailscale(e.target.checked)}
              className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4"
            />
            <span className="text-sm text-foreground">Tailscale IP (remote NVR)</span>
          </label>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setNvrModalOpen(false)}>Cancel</Button>
            <Button type="submit" loading={savingNvr}>{editingNvr ? "Save Changes" : "Add NVR"}</Button>
          </div>
          {nvrModalError && <p className="text-sm text-red-600 mt-2">{nvrModalError}</p>}
        </form>
      </Modal>

      {/* Import Channels Modal */}
      <Modal open={nvrImportModalOpen} onClose={() => setNvrImportModalOpen(false)} title={`Import Channels — ${nvrImportNvr?.name || ""}`}>
        <div className="space-y-4">
          <p className="text-sm text-secondary">
            Select channels (0–15) to import as cameras. Each channel will be linked to this NVR.
          </p>
          <div className="grid grid-cols-4 gap-2 max-h-60 overflow-y-auto border border-slate-200 rounded-lg p-3 bg-slate-50/50">
            {Array.from({ length: 16 }, (_, i) => (
              <label key={i} className="flex items-center gap-2 p-2 bg-white rounded border border-slate-200/60 cursor-pointer hover:bg-slate-50 transition-colors">
                <input
                  type="checkbox"
                  checked={nvrImportChannels.includes(i)}
                  onChange={() => toggleNvrImportChannel(i)}
                  className="rounded border-slate-300 text-primary focus:ring-primary h-4 w-4"
                />
                <span className="text-xs font-medium text-slate-700">Ch {i}</span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setNvrImportModalOpen(false)}>Cancel</Button>
            <Button onClick={handleImportNvrChannels} loading={nvrImporting} disabled={nvrImportChannels.length === 0}>
              Import Selected ({nvrImportChannels.length})
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal open={!!confirmDeleteNvr} onClose={() => setConfirmDeleteNvr(null)} title="Delete NVR" size="sm">
        <p className="text-sm text-secondary">
          Are you sure you want to delete this NVR? All linked cameras will be unlinked but not deleted.
        </p>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={() => setConfirmDeleteNvr(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => confirmDeleteNvr && handleDeleteNvr(confirmDeleteNvr)}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
