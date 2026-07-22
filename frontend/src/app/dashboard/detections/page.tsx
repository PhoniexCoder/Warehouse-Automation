"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { Card } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"

export default function DetectionsPage() {
  const [detections, setDetections] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const fetch = useCallback(async () => {
    try {
      const data = await api.getDetections({ limit: 200 })
      setDetections(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetch() }, [fetch])

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Detection History</h2>
        <p className="text-sm text-slate-500 mt-1">Raw detection events from the AI engine</p>
      </div>

      {detections.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-slate-400">
            <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <p className="font-medium">No detection events yet</p>
            <p className="text-sm mt-1">Detections will appear here once cameras are processing</p>
          </div>
        </Card>
      ) : (
        <Card padding={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/50">
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Timestamp</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Tracking ID</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Camera</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Carton Code</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Counted</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Bounding Box</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {detections.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50/30 transition-colors">
                    <td className="px-6 py-3 text-slate-500 text-xs whitespace-nowrap">
                      {format(new Date(d.timestamp), "MMM d, HH:mm:ss")}
                    </td>
                    <td className="px-6 py-3">
                      <code className="text-xs font-mono font-bold text-slate-900">#{d.tracking_id}</code>
                    </td>
                    <td className="px-6 py-3 text-slate-600 text-xs">{d.camera_id}</td>
                    <td className="px-6 py-3 text-xs font-mono text-slate-600">
                      {d.qr_data || <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-6 py-3">
                      <Badge variant={d.counted_status ? "success" : "warning"}>
                        {d.counted_status ? "Yes" : "No"}
                      </Badge>
                    </td>
                    <td className="px-6 py-3 text-xs font-mono text-slate-400">
                      {d.box_x},{d.box_y} {d.box_width}x{d.box_height}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
