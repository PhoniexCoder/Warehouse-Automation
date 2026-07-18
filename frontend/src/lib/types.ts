export interface ApiResponse<T = unknown> {
  success: boolean
  data: T | null
  error?: { code: string; message: string } | null
}

export interface TokenData {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface User {
  id: string
  username: string
  email: string
  role: string
  is_active: boolean
  created_at: string
}

export interface Warehouse {
  id: string
  name: string
  location: string
  created_at: string
}

export interface Camera {
  id: string
  warehouse_id: string
  camera_name: string
  camera_uuid: string
  stream_url: string
  status: string
  last_seen: string | null
  model_path: string | null
  roi: { x: number; y: number }[] | null
  health?: { status: string; frames?: number; [key: string]: any } | null
}

export interface InventoryItem {
  id: string
  product_code: string
  product_name: string
  quantity: number
  warehouse_id: string
  updated_at: string
}

export interface CountLog {
  id: string
  box_id: string
  camera_id: string
  movement_type: "ENTRY" | "EXIT"
  timestamp: string
}

export interface Alert {
  id: string
  type: "CAMERA_OFFLINE" | "INVALID_QR" | "DUPLICATE_COUNT" | "INVENTORY_MISMATCH"
  message: string
  severity: "info" | "warning" | "critical"
  timestamp: string
}

export interface DashboardSummary {
  total_boxes: number
  total_warehouses: number
  total_cameras: number
  total_alerts: number
  inventory_count: number
  recent_alerts: Alert[]
  cameras: Camera[]
  movement_summary: Record<string, number>
}
