"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import type { DashboardSummary } from "@/lib/types"
import { StatCard, Card } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"

const POLL_INTERVAL = 5000

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(true)

  const fetch = useCallback(async () => {
    try {
      const d = await api.getDashboard()
      setData(d)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()
    const interval = setInterval(fetch, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [fetch])

  if (loading) return <Spinner />
  if (!data) {
    return (
      <div className="text-center py-16">
        <p className="text-secondary">No dashboard data available</p>
      </div>
    )
  }

  const severityColor = (s: string) => {
    if (s === "critical") return "danger"
    if (s === "warning") return "warning"
    return "info"
  }

  const alertTypeIcon = (t: string) => {
    if (t === "CAMERA_OFFLINE") return "🔴"
    if (t === "INVALID_QR") return "⚠️"
    if (t === "DUPLICATE_COUNT") return "🔁"
    if (t === "INVENTORY_MISMATCH") return "📦"
    return "🔔"
  }

  const onlineCameras = data.cameras?.filter((c) => c.status === "online").length || 0
  const totalCameras = data.cameras?.length || 0

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Dashboard</h2>
        <p className="text-sm text-secondary mt-1">
          Real-time warehouse monitoring &mdash; auto-refreshes every 5s
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Boxes"
          value={data.total_boxes ?? 0}
          color="primary"
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
            </svg>
          }
        />
        <StatCard
          label="Active Cameras"
          value={`${onlineCameras}/${totalCameras}`}
          color="success"
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          }
        />
        <StatCard
          label="Inventory Items"
          value={data.inventory_count ?? 0}
          color="info"
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
            </svg>
          }
        />
        <StatCard
          label="Active Alerts"
          value={data.total_alerts ?? 0}
          color={data.total_alerts > 0 ? "danger" : "success"}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          }
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h3 className="text-base font-semibold text-foreground mb-4">Camera Status</h3>
          {(!data.cameras || data.cameras.length === 0) ? (
            <div className="text-center py-8 text-sm text-secondary">No cameras registered</div>
          ) : (
            <div className="space-y-2">
              {data.cameras.slice(0, 8).map((cam) => (
                <div key={cam.id} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-gray-50">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${cam.status === "online" ? "bg-success" : "bg-danger"}`} />
                    <span className="text-sm font-medium text-foreground">{cam.camera_name}</span>
                  </div>
                  <Badge variant={cam.status === "online" ? "success" : "danger"}>
                    {cam.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h3 className="text-base font-semibold text-foreground mb-4">Recent Alerts</h3>
          {(!data.recent_alerts || data.recent_alerts.length === 0) ? (
            <div className="text-center py-8 text-sm text-secondary">No recent alerts</div>
          ) : (
            <div className="space-y-2">
              {data.recent_alerts.slice(0, 8).map((alert) => (
                <div key={alert.id} className="flex items-start gap-3 py-2 px-3 rounded-lg hover:bg-gray-50">
                  <span className="text-base shrink-0 mt-0.5">{alertTypeIcon(alert.type)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-foreground truncate">{alert.message}</p>
                    <p className="text-xs text-secondary mt-0.5">
                      {format(new Date(alert.timestamp), "MMM d, HH:mm:ss")}
                    </p>
                  </div>
                  <Badge variant={severityColor(alert.severity)}>{alert.severity}</Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card>
        <h3 className="text-base font-semibold text-foreground mb-4">Movement Summary</h3>
        {(!data.movement_summary || Object.keys(data.movement_summary).length === 0) ? (
          <div className="text-center py-8 text-sm text-secondary">No movement data</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(data.movement_summary).map(([type, count]) => (
              <div key={type} className="text-center p-4 bg-gray-50 rounded-lg">
                <p className="text-2xl font-bold text-foreground">{count}</p>
                <p className="text-xs font-medium text-secondary mt-1">{type}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
