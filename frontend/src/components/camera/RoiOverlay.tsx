"use client"

import { useRef, useEffect, useState, useCallback } from "react"

interface RoiOverlayProps {
  mjpegUrl: string
  roi: { x: number; y: number }[] | null
  onRoiChange: (roi: { x: number; y: number }[] | null) => void
  drawing: boolean
}

export function RoiOverlay({ mjpegUrl, roi, onRoiChange, drawing }: RoiOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)
  const [points, setPoints] = useState<{ x: number; y: number }[]>([])
  const [hoverPoint, setHoverPoint] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    setPoints(roi || [])
  }, [roi])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img || !img.complete || !img.naturalWidth) return

    const ctx = canvas.getContext("2d")
    if (!ctx) return

    canvas.width = img.clientWidth
    canvas.height = img.clientHeight

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    if (points.length === 0) return

    const cx = points.map((p) => ({
      x: p.x * canvas.width,
      y: p.y * canvas.height,
    }))

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
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2)
      ctx.fillStyle = "#22c55e"
      ctx.fill()
      ctx.strokeStyle = "#fff"
      ctx.lineWidth = 1.5
      ctx.stroke()
    }

    if (hoverPoint && cx.length > 0) {
      const hx = hoverPoint.x * canvas.width
      const hy = hoverPoint.y * canvas.height
      ctx.beginPath()
      ctx.moveTo(cx[cx.length - 1].x, cx[cx.length - 1].y)
      ctx.lineTo(hx, hy)
      ctx.strokeStyle = "rgba(34, 197, 94, 0.4)"
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      ctx.stroke()
      ctx.setLineDash([])
    }
  }, [points, hoverPoint])

  useEffect(() => {
    const img = new Image()
    img.crossOrigin = "anonymous"
    img.src = mjpegUrl
    img.onload = () => {
      imgRef.current = img
      draw()
    }
    return () => { imgRef.current = null }
  }, [mjpegUrl, draw])

  useEffect(() => {
    const interval = setInterval(draw, 100)
    return () => clearInterval(interval)
  }, [draw])

  const getRelativePos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    return {
      x: (e.clientX - rect.left) / canvas.clientWidth,
      y: (e.clientY - rect.top) / canvas.clientHeight,
    }
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    const pos = getRelativePos(e)
    const newPoints = [...points, pos]
    setPoints(newPoints)
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
    <div className="relative w-full h-full">
      <img
        src={mjpegUrl}
        alt="Camera preview"
        className="w-full h-full object-contain"
        crossOrigin="anonymous"
      />
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full cursor-crosshair"
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverPoint(null)}
        onDoubleClick={handleDoubleClick}
      />
    </div>
  )
}
