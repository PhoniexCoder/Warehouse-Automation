"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { Card } from "@/components/ui/Card"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [actionFilter, setActionFilter] = useState("")

  const fetch = useCallback(async () => {
    try {
      const params: Record<string, any> = {}
      if (actionFilter) params.action = actionFilter
      const data = await api.getAuditLogs(params)
      setLogs(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [actionFilter])

  useEffect(() => { fetch() }, [fetch])

  const actions = [...new Set(logs.map((l) => l.action?.split(".")[0] || l.action))].sort()

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Audit Logs</h2>
        <p className="text-sm text-slate-500 mt-1">User activity trail across the system</p>
      </div>

      <div className="flex items-center gap-3">
        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className="input-field w-auto text-sm"
        >
          <option value="">All Actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <span className="text-xs text-slate-400 font-medium">{logs.length} entries</span>
      </div>

      {logs.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-slate-400">
            <p className="font-medium">No audit log entries yet</p>
            <p className="text-sm mt-1">Activity will be recorded as users interact with the system</p>
          </div>
        </Card>
      ) : (
        <Card padding={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/50">
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Timestamp</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">User ID</th>
                  <th className="text-left px-6 py-3 font-semibold text-slate-600">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-50/30 transition-colors">
                    <td className="px-6 py-3 text-slate-500 text-xs whitespace-nowrap">
                      {format(new Date(log.timestamp), "MMM d, yyyy HH:mm:ss")}
                    </td>
                    <td className="px-6 py-3">
                      <code className="text-xs font-mono text-slate-700">{log.user_id || "system"}</code>
                    </td>
                    <td className="px-6 py-3">
                      <code className="text-xs font-mono text-slate-600 bg-slate-50 px-2 py-0.5 rounded">
                        {log.action}
                      </code>
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
