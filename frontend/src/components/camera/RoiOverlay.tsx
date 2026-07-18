"use client"

import { useRef, useEffect, useState, useCallback } from "react"

interface RoiOverlayProps {
  mjpegUrl: string
  roi: { x: number; y: number }[] | null
  onRoiChange: (roi: { x: number; y: number }[] | null) => void
  drawing: boolean
}

export function RoiOverlay({ mjpegUrl, roi, onRoiChange, drawing }: RoiOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const [points, setPoints] = useState<{ x: number; y: number }[]>([])
  const [hoverPoint, setHoverPoint] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    setPoints(roi || [])
  }, [roi])

  useEffect(() => {
    let raf: number

    function tick() {
      const canvas = canvasRef.current
      const img = imgRef.current
      const container = containerRef.current
      if (!canvas || !img || !container) {
        raf = requestAnimationFrame(tick)
        return
      }

      const cw = container.clientWidth
      const ch = container.clientHeight
      if (cw === 0 || ch === 0) {
        raf = requestAnimationFrame(tick)
        return
      }

      canvas.width = cw
      canvas.height = ch

      const ctx = canvas.getContext("2d")
      if (!ctx) {
        raf = requestAnimationFrame(tick)
        return
      }

      ctx.clearRect(0, 0, cw, ch)

      if (points.length > 0) {
        const cx = points.map((p) => ({ x: p.x * cw, y: p.y * ch }))

        ctx.beginPath()
        ctx.moveTo(cx[0].x, cx[0].y)
        for (let i = 1; i < cx.length; i++) {
          ctx.lineTo(cx[i].x, cx[i].y)
        }
        if (cx.length > 2) {
          ctx.closePath()
          ctx.fillStyle = "rgba(34, 197, 94, 0.15)"
          ctx.fill()
        }
        ctx.strokeStyle = "rgba(34, 197, 94, 0.8)"
        ctx.lineWidth = 2
        ctx.stroke()

        for (const p of cx) {
          ctx.beginPath()
          ctx.arc(p.x, p.y, 5, 0, Math.PI * 2)
          ctx.fillStyle = "#22c55e"
          ctx.fill()
          ctx.strokeStyle = "#fff"
          ctx.lineWidth = 2
          ctx.stroke()
        }

        if (hoverPoint) {
          const hx = hoverPoint.x * cw
          const hy = hoverPoint.y * ch
          ctx.beginPath()
          ctx.moveTo(cx[cx.length - 1].x, cx[cx.length - 1].y)
          ctx.lineTo(hx, hy)
          ctx.strokeStyle = "rgba(34, 197, 94, 0.5)"
          ctx.lineWidth = 1.5
          ctx.setLineDash([5, 5])
          ctx.stroke()
          ctx.setLineDash([])
        }
      }

      raf = requestAnimationFrame(tick)
    }

    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [points, hoverPoint])

  const getRelativePos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    }
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    setPoints((prev) => [...prev, getRelativePos(e)])
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing || points.length === 0) return
    setHoverPoint(getRelativePos(e))
  }

  const handleDoubleClick = () => {
    if (!drawing || points.length < 3) return
    setHoverPoint(null)
    onRoiChange(points)
  }

  return (
    <div ref={containerRef} className="relative w-full h-full bg-black">
      <img
        ref={imgRef}
        src={mjpegUrl}
        alt="Camera preview"
        className="w-full h-full object-contain"
      />
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        style={{ cursor: drawing ? "crosshair" : "default" }}
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverPoint(null)}
        onDoubleClick={handleDoubleClick}
      />
    </div>
  )
}
