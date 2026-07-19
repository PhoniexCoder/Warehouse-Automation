"use client"

import { useEffect, useRef, useState } from "react"
import { CameraStream, type StreamStatus } from "@/lib/stream"

interface LiveCameraPreviewProps {
  cameraId: string
  isActive: boolean
  className?: string
}

const STATUS_LABELS: Record<StreamStatus, string> = {
  connecting: "connecting",
  live: "live",
  reconnecting: "reconnecting",
  error: "error",
  fallback: "streaming",
}

const STATUS_COLORS: Record<StreamStatus, string> = {
  connecting: "bg-yellow-500",
  live: "bg-green-500",
  reconnecting: "bg-yellow-500",
  error: "bg-red-500",
  fallback: "bg-blue-500",
}

export function LiveCameraPreview({ cameraId, isActive, className }: LiveCameraPreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<CameraStream | null>(null)
  const [status, setStatus] = useState<StreamStatus>("connecting")

  useEffect(() => {
    if (!isActive || !canvasRef.current) return

    const apiKey = process.env.NEXT_PUBLIC_CV_ENGINE_KEY || ""
    const stream = new CameraStream(cameraId, canvasRef.current, {
      apiKey,
      onStatusChange: setStatus,
    })
    streamRef.current = stream
    stream.start()

    return () => {
      stream.destroy()
      streamRef.current = null
    }
  }, [cameraId, isActive])

  return (
    <div className={`relative ${className || ""}`}>
      <canvas
        ref={canvasRef}
        className="w-full h-full object-contain"
        width={1920}
        height={1080}
      />
      {/* Status badge overlay */}
      <div className="absolute top-2 right-2 flex items-center gap-1.5 bg-black/60 rounded-full px-2 py-0.5">
        <div className={`w-1.5 h-1.5 rounded-full ${STATUS_COLORS[status]}`} />
        <span className="text-[10px] text-white font-mono uppercase">
          {STATUS_LABELS[status]}
        </span>
      </div>
    </div>
  )
}
