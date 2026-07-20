"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import { Card } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"

export default function StreamsPage() {
  const [streams, setStreams] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)

  const fetch = useCallback(async () => {
    try {
      const data = await api.getGo2rtcStreams()
      setStreams(data || {})
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()
    const interval = setInterval(fetch, 15000)
    return () => clearInterval(interval)
  }, [fetch])

  if (loading) return <Spinner />

  const entries = Object.entries(streams)

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Stream Status</h2>
        <p className="text-sm text-slate-500 mt-1">Live go2rtc stream health &mdash; auto-refreshes every 15s</p>
      </div>

      {entries.length === 0 ? (
        <Card>
          <div className="text-center py-12 text-slate-400">
            <p className="font-medium">No active streams</p>
            <p className="text-sm mt-1">Streams will appear when cameras are connected via go2rtc</p>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {entries.map(([name, info]) => {
            const isRunning = info?.status === "running" || !!info?.producers?.length
            return (
              <Card key={name}>
                <div className="flex items-start justify-between mb-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-slate-900 text-sm truncate">{name}</h3>
                    {info?.url && (
                      <p className="text-[10px] font-mono text-slate-400 truncate mt-0.5">{info.url}</p>
                    )}
                  </div>
                  <Badge variant={isRunning ? "success" : "danger"}>
                    {isRunning ? "Running" : "Stopped"}
                  </Badge>
                </div>
                {info?.producers && info.producers.length > 0 && (
                  <div className="space-y-1.5 mt-2 pt-2 border-t border-slate-100">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Producers</p>
                    {info.producers.map((p: any, i: number) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="text-slate-600 font-mono">{p.remote_addr || "local"}</span>
                        <span className="text-slate-400">{p.type || "unknown"}</span>
                      </div>
                    ))}
                  </div>
                )}
                {info?.clients && info.clients.length > 0 && (
                  <div className="space-y-1.5 mt-2 pt-2 border-t border-slate-100">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Clients ({info.clients.length})</p>
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
