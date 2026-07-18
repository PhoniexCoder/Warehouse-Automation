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
  const imgRef = useRef<HTMLImageElement | null>(null)
  const [points, setPoints] = useState<{ x: number; y: number }[]>([])
  const [hoverPoint, setHoverPoint] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    setPoints(roi || [])
  }, [roi])

  const imgToCanvas = useCallback((imgX: number, imgY: number, imgW: number, imgH: number) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const scaleX = canvas.width / imgW
    const scaleY = canvas.height / imgH
    return { x: imgX * scaleX, y: imgY * scaleY }
  }, [])

  const canvasToImg = useCallback((canvasX: number, canvasY: number) => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img || !img.naturalWidth || !img.naturalHeight) return { x: 0, y: 0 }
    const scaleX = img.naturalWidth / canvas.width
    const scaleY = img.naturalHeight / canvas.height
    return { x: canvasX * scaleX, y: canvasY * scaleY }
  }, [])

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

    const canvasPoints = points.map((p) =>
      imgToCanvas(p.x, p.naturalWidth || p.x, p.y, p.naturalHeight || p.y)
    ).map((cp, i) => ({
      x: (points[i].x) * canvas.width,
      y: (points[i].y) * canvas.height,
    }))

    ctx.beginPath()
    ctx.moveTo(canvasPoints[0].x, canvasPoints[0].y)
    for (let i = 1; i < canvasPoints.length; i++) {
      ctx.lineTo(canvasPoints[i].x, canvasPoints[i].y)
    }
    if (canvasPoints.length > 2) {
      ctx.closePath()
      ctx.fillStyle = "rgba(34, 197, 94, 0.15)"
      ctx.fill()
    }
    ctx.strokeStyle = "rgba(34, 197, 94, 0.8)"
    ctx.lineWidth = 2
    ctx.stroke()

    for (const cp of canvasPoints) {
      ctx.beginPath()
      ctx.arc(cp.x, cp.y, 4, 0, Math.PI * 2)
      ctx.fillStyle = "#22c55e"
      ctx.fill()
      ctx.strokeStyle = "#fff"
      ctx.lineWidth = 1.5
      ctx.stroke()
    }

    if (hoverPoint && points.length > 0) {
      const hx = hoverPoint.x * canvas.width
      const hy = hoverPoint.y * canvas.height
      ctx.beginPath()
      ctx.moveTo(canvasPoints[canvasPoints.length - 1].x, canvasPoints[canvasPoints.length - 1].y)
      ctx.lineTo(hx, hy)
      ctx.strokeStyle = "rgba(34, 197, 94, 0.4)"
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      ctx.stroke()
      ctx.setLineDash([])
    }
  }, [points, hoverPoint, imgToCanvas])

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

  const handleDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing || points.length < 3) return
    setHoverPoint(null)
    onRoiChange(points)
  }

  return (
    <div ref={containerRef} className="relative w-full h-full">
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
