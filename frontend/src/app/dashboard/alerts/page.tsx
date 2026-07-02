"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import type { Alert } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"
import clsx from "clsx"

const POLL_INTERVAL = 10000

const alertTypeMeta: Record<string, { label: string; icon: string; color: string }> = {
  CAMERA_OFFLINE: { label: "Camera Offline", icon: "🔴", color: "danger" },
  INVALID_QR: { label: "Invalid QR", icon: "⚠️", color: "warning" },
  DUPLICATE_COUNT: { label: "Duplicate Count", icon: "🔁", color: "info" },
  INVENTORY_MISMATCH: { label: "Inventory Mismatch", icon: "📦", color: "warning" },
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [typeFilter, setTypeFilter] = useState<string>("all")
  const [severityFilter, setSeverityFilter] = useState<string>("all")

  const fetch = useCallback(async () => {
    try {
      const params: Record<string, string> = {}
      if (typeFilter !== "all") params.alert_type = typeFilter
      if (severityFilter !== "all") params.severity = severityFilter
      const data = await api.getAlerts(params)
      setAlerts(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [typeFilter, severityFilter])

  useEffect(() => {
    fetch()
    const interval = setInterval(fetch, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [fetch])

  const severityColor = (s: string) => {
    if (s === "critical") return "danger"
    if (s === "warning") return "warning"
    return "info"
  }

  const types = [
    { value: "all", label: "All Types" },
    { value: "CAMERA_OFFLINE", label: "Camera Offline" },
    { value: "INVALID_QR", label: "Invalid QR" },
    { value: "DUPLICATE_COUNT", label: "Duplicate Count" },
    { value: "INVENTORY_MISMATCH", label: "Inventory Mismatch" },
  ]

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Alerts</h2>
        <p className="text-sm text-secondary mt-1">System alerts and notifications &mdash; auto-refreshes every 10s</p>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="flex gap-1 p-1 bg-gray-100 rounded-lg">
          {types.map((t) => (
            <button
              key={t.value}
              onClick={() => setTypeFilter(t.value)}
              className={clsx(
                "px-3 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-all",
                typeFilter === t.value
                  ? "bg-white text-foreground shadow-sm"
                  : "text-secondary hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="input-field w-auto text-sm"
        >
          <option value="all">All Severity</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      {alerts.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-secondary">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="font-medium">No alerts</p>
            <p className="text-sm mt-1">All systems running normally</p>
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert) => {
            const meta = alertTypeMeta[alert.type] || { label: alert.type, icon: "🔔", color: "default" }
            return (
              <Card key={alert.id} padding={false}>
                <div className="flex items-start gap-4 p-4 sm:p-5">
                  <span className="text-xl shrink-0 mt-0.5">{meta.icon}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-foreground text-sm">{meta.label}</span>
                      <Badge variant={severityColor(alert.severity) as "danger" | "warning" | "info"}>
                        {alert.severity}
                      </Badge>
                    </div>
                    <p className="text-sm text-foreground mt-1.5">{alert.message}</p>
                    <p className="text-xs text-secondary mt-1.5">
                      {format(new Date(alert.timestamp), "MMM d, yyyy HH:mm:ss")}
                    </p>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
