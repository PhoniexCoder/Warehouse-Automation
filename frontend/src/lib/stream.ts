/**
 * WebSocket client for live camera frame streaming from cv-engine.
 *
 * Connects directly to cv-engine:8000 via WebSocket, receives raw JPEG binary
 * frames at ~5 FPS, and renders them to an HTMLCanvasElement.
 *
 * Falls back to MJPEG <img> if WebSocket fails.
 */

const RECONNECT_BASE_DELAY = 1000
const RECONNECT_MAX_DELAY = 15000
const FRAME_TIMEOUT_MS = 8000

export type StreamStatus = "connecting" | "live" | "reconnecting" | "error" | "fallback"

export class CameraStream {
  private cameraId: string
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D | null = null
  private ws: WebSocket | null = null
  private img: HTMLImageElement | null = null
  private status: StreamStatus = "connecting"
  private stop = false
  private reconnectDelay = RECONNECT_BASE_DELAY
  private consecutiveErrors = 0
  private frameTimer: ReturnType<typeof setTimeout> | null = null
  private onStatusChange?: (status: StreamStatus) => void
  private apiKey: string

  constructor(
    cameraId: string,
    canvas: HTMLCanvasElement,
    options?: {
      apiKey?: string
      onStatusChange?: (status: StreamStatus) => void
    },
  ) {
    this.cameraId = cameraId
    this.canvas = canvas
    this.ctx = canvas.getContext("2d")
    this.apiKey = options?.apiKey || ""
    this.onStatusChange = options?.onStatusChange
  }

  start(): void {
    this.stop = false
    this.connectWebSocket()
  }

  destroy(): void {
    this.stop = true
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    if (this.img) {
      this.img.src = ""
      this.img = null
    }
    if (this.frameTimer) {
      clearTimeout(this.frameTimer)
      this.frameTimer = null
    }
  }

  private setStatus(s: StreamStatus): void {
    if (this.status !== s) {
      this.status = s
      this.onStatusChange?.(s)
    }
  }

  private getWsUrl(): string {
    if (typeof window === "undefined") return ""
    const hostname = window.location.hostname
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const params = this.apiKey ? `?key=${encodeURIComponent(this.apiKey)}` : ""
    return `${protocol}//${hostname}:8000/api/v1/stream/ws/${this.cameraId}${params}`
  }

  private getMjpegUrl(): string {
    if (typeof window === "undefined") return ""
    const hostname = window.location.hostname
    return `http://${hostname}:8000/api/v1/stream/${this.cameraId}`
  }

  private connectWebSocket(): void {
    if (this.stop) return

    this.setStatus("connecting")
    const url = this.getWsUrl()
    if (!url) return

    try {
      this.ws = new WebSocket(url)
      this.ws.binaryType = "arraybuffer"
    } catch {
      this.fallbackToMjpeg()
      return
    }

    this.ws.onopen = () => {
      this.consecutiveErrors = 0
      this.reconnectDelay = RECONNECT_BASE_DELAY
      this.setStatus("live")
      this.startFrameWatchdog()
    }

    this.ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        this.renderJpegFrame(event.data)
        this.resetFrameWatchdog()
      }
    }

    this.ws.onerror = () => {
      this.consecutiveErrors++
    }

    this.ws.onclose = () => {
      if (this.stop) return
      if (this.frameTimer) {
        clearTimeout(this.frameTimer)
        this.frameTimer = null
      }

      if (this.consecutiveErrors >= 3) {
        this.fallbackToMjpeg()
      } else {
        this.setStatus("reconnecting")
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_DELAY)
        setTimeout(() => this.connectWebSocket(), this.reconnectDelay)
      }
    }
  }

  private fallbackToMjpeg(): void {
    if (this.stop) return
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.setStatus("fallback")

    this.img = new Image()
    this.img.crossOrigin = "anonymous"
    this.img.src = this.getMjpegUrl()

    this.img.onload = () => {
      this.drawImageToCanvas(this.img!)
    }

    this.img.onerror = () => {
      this.setStatus("error")
    }

    // For MJPEG fallback, we poll the img element
    const pollInterval = setInterval(() => {
      if (this.stop || !this.img) {
        clearInterval(pollInterval)
        return
      }
      if (this.img.complete && this.img.naturalWidth > 0) {
        this.drawImageToCanvas(this.img)
      }
    }, 100)
  }

  private renderJpegFrame(buffer: ArrayBuffer): void {
    const blob = new Blob([buffer], { type: "image/jpeg" })
    const url = URL.createObjectURL(blob)
    const img = new Image()

    img.onload = () => {
      this.drawImageToCanvas(img)
      URL.revokeObjectURL(url)
    }

    img.onerror = () => {
      URL.revokeObjectURL(url)
    }

    img.src = url
  }

  private drawImageToCanvas(img: HTMLImageElement | HTMLImageElement): void {
    if (!this.ctx || !this.canvas) return

    // Match canvas size to image
    if (this.canvas.width !== img.naturalWidth || this.canvas.height !== img.naturalHeight) {
      this.canvas.width = img.naturalWidth || 1920
      this.canvas.height = img.naturalHeight || 1080
    }

    this.ctx.drawImage(img, 0, 0, this.canvas.width, this.canvas.height)
  }

  private startFrameWatchdog(): void {
    this.resetFrameWatchdog()
  }

  private resetFrameWatchdog(): void {
    if (this.frameTimer) clearTimeout(this.frameTimer)
    this.frameTimer = setTimeout(() => {
      // No frames received for a while — reconnect
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.close()
      }
    }, FRAME_TIMEOUT_MS)
  }
}
