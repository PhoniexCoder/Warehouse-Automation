"use client"

import { useRef, useEffect, useState } from "react"

interface RoiOverlayProps {
  mjpegUrl: string
  roi: { x: number; y: number }[] | null
  onRoiChange: (roi: { x: number; y: number }[] | null) => void
  drawing: boolean
}

export function RoiOverlay({ mjpegUrl, roi, onRoiChange, drawing }: RoiOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pointsRef = useRef<{ x: number; y: number }[]>([])
  const hoverRef = useRef<{ x: number; y: number } | null>(null)
  const drawingRef = useRef(drawing)
  const [, forceRender] = useState(0)

  useEffect(() => {
    pointsRef.current = roi || []
    forceRender((n) => n + 1)
  }, [roi])

  useEffect(() => {
    drawingRef.current = drawing
  }, [drawing])

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    let raf: number

    const tick = () => {
      const cw = container.clientWidth
      const ch = container.clientHeight

      if (cw > 0 && ch > 0 && (canvas.width !== cw || canvas.height !== ch)) {
        canvas.width = cw
        canvas.height = ch
      }

      const ctx = canvas.getContext("2d")
      if (!ctx || canvas.width === 0 || canvas.height === 0) {
        raf = requestAnimationFrame(tick)
        return
      }

      const w = canvas.width
      const h = canvas.height
      ctx.clearRect(0, 0, w, h)

      const pts = pointsRef.current
      if (pts.length > 0) {
        const cx = pts.map((p) => ({ x: p.x * w, y: p.y * h }))

        ctx.beginPath()
        ctx.moveTo(cx[0].x, cx[0].y)
        for (let i = 1; i < cx.length; i++) {
          ctx.lineTo(cx[i].x, cx[i].y)
        }
        if (cx.length > 2) {
          ctx.closePath()
          ctx.fillStyle = "rgba(34, 197, 94, 0.2)"
          ctx.fill()
        }
        ctx.strokeStyle = "rgba(34, 197, 94, 0.9)"
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

        const hp = hoverRef.current
        if (hp) {
          const last = cx[cx.length - 1]
          ctx.beginPath()
          ctx.moveTo(last.x, last.y)
          ctx.lineTo(hp.x * w, hp.y * h)
          ctx.strokeStyle = "rgba(34, 197, 94, 0.5)"
          ctx.lineWidth = 1.5
          ctx.setLineDash([5, 5])
          ctx.stroke()
          ctx.setLineDash([])
        }
      }

      if (drawingRef.current && canvas.style.cursor !== "crosshair") {
        canvas.style.cursor = "crosshair"
      } else if (!drawingRef.current && canvas.style.cursor !== "default") {
        canvas.style.cursor = "default"
      }

      raf = requestAnimationFrame(tick)
    }

    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  function getPos(e: React.MouseEvent<HTMLCanvasElement>): { x: number; y: number } {
    const rect = canvasRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    }
  }

  function handleClick(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return
    const pos = getPos(e)
    pointsRef.current = [...pointsRef.current, pos]
    forceRender((n) => n + 1)
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!drawingRef.current || pointsRef.current.length === 0) return
    hoverRef.current = getPos(e)
  }

  function handleDoubleClick() {
    if (!drawingRef.current || pointsRef.current.length < 3) return
    hoverRef.current = null
    onRoiChange([...pointsRef.current])
  }

  return (
    <div
      ref={containerRef}
      style={{ position: "relative", width: "100%", height: "100%", minHeight: 200, background: "#000" }}
    >
      <img
        src={mjpegUrl}
        alt="Camera preview"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "contain",
          pointerEvents: "none",
        }}
      />
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => { hoverRef.current = null }}
        onDoubleClick={handleDoubleClick}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          zIndex: 10,
        }}
      />
    </div>
  )
}
