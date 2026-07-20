"use client"

import { useState } from "react"
import { api } from "@/lib/api"
import { Card } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"

type SearchMode = "tracking" | "qr"

export default function BoxesPage() {
  const [mode, setMode] = useState<SearchMode>("tracking")
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<any[] | null>(null)
  const [error, setError] = useState("")
  const [detail, setDetail] = useState<any | null>(null)

  async function handleSearch() {
    if (!query.trim()) return
    setLoading(true)
    setError("")
    setDetail(null)
    try {
      if (mode === "tracking") {
        const id = parseInt(query, 10)
        if (isNaN(id)) { setError("Enter a numeric tracking ID"); setLoading(false); return }
        const box = await api.getBoxByTrackingId(id)
        setResults(box ? [box] : [])
      } else {
        const boxes = await api.getBoxesByQr(query)
        setResults(boxes)
      }
    } catch {
      setError("Search failed")
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  async function openDetail(boxId: string) {
    setLoading(true)
    try {
      const d = await api.getBoxDetail(boxId)
      setDetail(d)
    } catch {
      setError("Failed to load box details")
    } finally {
      setLoading(false)
    }
  }

  const statusColor = (s: string) => {
    if (s === "IN_TRANSIT") return "warning" as const
    if (s === "STORED") return "info" as const
    if (s === "DISPATCHED") return "success" as const
    if (s === "LOST") return "danger" as const
    return "default" as const
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Box Search</h2>
        <p className="text-sm text-slate-500 mt-1">Look up carton boxes by tracking ID or QR code</p>
      </div>

      <Card>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <div className="flex gap-1 p-1 bg-gray-100 rounded-lg">
            <button
              onClick={() => { setMode("tracking"); setResults(null); setDetail(null) }}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${mode === "tracking" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
            >
              Tracking ID
            </button>
            <button
              onClick={() => { setMode("qr"); setResults(null); setDetail(null) }}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${mode === "qr" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
            >
              QR Code
            </button>
          </div>
          <div className="flex-1 flex gap-2 w-full sm:w-auto">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="input-field flex-1"
              placeholder={mode === "tracking" ? "Enter tracking ID (e.g. 42)" : "Enter QR data (e.g. BOX-1024)"}
            />
            <button
              onClick={handleSearch}
              disabled={loading}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold transition disabled:opacity-50"
            >
              {loading ? "Searching..." : "Search"}
            </button>
          </div>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </Card>

      {detail ? (
        <div className="space-y-4">
          <button
            onClick={() => setDetail(null)}
            className="text-xs text-blue-600 hover:underline font-medium"
          >
            &larr; Back to results
          </button>
          <Card>
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Box ID</p>
                  <p className="text-sm font-mono font-bold text-slate-900 mt-0.5">{detail.id?.slice(0, 8)}</p>
                </div>
                <div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Tracking ID</p>
                  <p className="text-sm font-mono font-bold text-slate-900 mt-0.5">#{detail.tracking_id}</p>
                </div>
                <div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">QR Data</p>
                  <p className="text-sm font-mono text-slate-700 mt-0.5">{detail.qr_data || "—"}</p>
                </div>
                <div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Status</p>
                  <p className="mt-0.5"><Badge variant={statusColor(detail.status)}>{detail.status}</Badge></p>
                </div>
              </div>
              <div className="border-t border-slate-100 pt-4">
                <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Count Logs</p>
                {detail.count_logs?.length > 0 ? (
                  <div className="space-y-2">
                    {detail.count_logs.map((log: any) => (
                      <div key={log.id} className="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2 text-xs">
                        <span className="font-mono text-slate-600">{format(new Date(log.timestamp), "MMM d, HH:mm:ss")}</span>
                        <span className="font-bold">{log.camera_id}</span>
                        <Badge variant={log.movement_type === "ENTRY" ? "success" : "warning"}>
                          {log.movement_type}
                        </Badge>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">No count logs for this box</p>
                )}
              </div>
            </div>
          </Card>
        </div>
      ) : results !== null ? (
        <div className="space-y-3">
          <p className="text-xs text-slate-400 font-medium">{results.length} result{results.length !== 1 ? "s" : ""}</p>
          {results.length === 0 ? (
            <Card>
              <div className="text-center py-8 text-slate-400">
                <p className="font-medium">No box found</p>
                <p className="text-sm mt-1">Try a different search term</p>
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {results.map((box) => (
                <Card key={box.id}>
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <p className="text-xs font-mono font-bold text-slate-900">#{box.tracking_id}</p>
                      <p className="text-[10px] text-slate-400 font-mono mt-0.5">{box.id?.slice(0, 8)}</p>
                    </div>
                    <Badge variant={statusColor(box.status)}>{box.status}</Badge>
                  </div>
                  {box.qr_data && (
                    <p className="text-xs text-slate-500 mb-3">QR: {box.qr_data}</p>
                  )}
                  <p className="text-[10px] text-slate-400 mb-2">Camera: {box.camera_id}</p>
                  <p className="text-[10px] text-slate-400 mb-3">Created: {format(new Date(box.created_at), "MMM d, yyyy")}</p>
                  <button
                    onClick={() => openDetail(box.id)}
                    className="w-full text-center px-3 py-1.5 bg-slate-50 hover:bg-slate-100 rounded-lg text-xs font-bold text-slate-600 transition"
                  >
                    View Details
                  </button>
                </Card>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
