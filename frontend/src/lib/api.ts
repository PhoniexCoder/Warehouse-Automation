import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from "axios"
import type { ApiResponse, Alert, Camera, CountLog, DashboardSummary, InventoryItem, TokenData, User, Warehouse } from "./types"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1"

function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("access_token")
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("refresh_token")
}

function setTokens(access: string, refresh: string): void {
  localStorage.setItem("access_token", access)
  localStorage.setItem("refresh_token", refresh)
}

function clearTokens(): void {
  localStorage.removeItem("access_token")
  localStorage.removeItem("refresh_token")
  localStorage.removeItem("user")
}

const client: AxiosInstance = axios.create({
  baseURL: API_URL,
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
})

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken()
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let isRefreshing = false
let pendingQueue: Array<{ resolve: (t: string) => void; reject: (e: unknown) => void }> = []

async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) throw new Error("No refresh token")

  const res = await axios.post<TokenData & ApiResponse>(
    `${API_URL}/refresh`,
    { refresh_token: refreshToken },
  )
  const data = res.data.data as TokenData
  setTokens(data.access_token, data.refresh_token)
  return data.access_token
}

client.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingQueue.push({
            resolve: (token: string) => {
              if (originalRequest.headers) originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(client(originalRequest))
            },
            reject,
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await refreshAccessToken()
        pendingQueue.forEach((p) => p.resolve(newToken))
        pendingQueue = []
        if (originalRequest.headers) originalRequest.headers.Authorization = `Bearer ${newToken}`
        return client(originalRequest)
      } catch {
        clearTokens()
        pendingQueue.forEach((p) => p.reject(error))
        pendingQueue = []
        if (typeof window !== "undefined") {
          window.location.href = "/login"
        }
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }
    return Promise.reject(error)
  },
)

export const api = {
  setTokens,
  clearTokens,
  getToken,
  getUser: (): User | null => {
    if (typeof window === "undefined") return null
    const raw = localStorage.getItem("user")
    return raw ? JSON.parse(raw) : null
  },
  setUser: (user: User) => localStorage.setItem("user", JSON.stringify(user)),

  login: async (username: string, password: string): Promise<TokenData> => {
    const res = await client.post<ApiResponse>("/login", { username, password })
    const data = res.data.data as TokenData
    setTokens(data.access_token, data.refresh_token)
    return data
  },

  getMe: async (): Promise<User> => {
    const res = await client.get<ApiResponse>("/me")
    return res.data.data as User
  },

  register: async (payload: { username: string; email: string; password: string; role: string }) => {
    const res = await client.post<ApiResponse>("/register", payload)
    return res.data.data as User
  },

  getDashboard: async (): Promise<DashboardSummary> => {
    const res = await client.get<ApiResponse>("/dashboard/summary")
    return res.data.data as DashboardSummary
  },

  // Warehouses
  getWarehouses: async (): Promise<Warehouse[]> => {
    const res = await client.get<ApiResponse>("/warehouses")
    return (res.data.data as Warehouse[]) || []
  },
  createWarehouse: async (data: { name: string; location: string }): Promise<Warehouse> => {
    const res = await client.post<ApiResponse>("/warehouses", data)
    return res.data.data as Warehouse
  },
  deleteWarehouse: async (id: string): Promise<void> => {
    await client.delete(`/warehouses/${id}`)
  },

  // Cameras
  getCameras: async (): Promise<Camera[]> => {
    const res = await client.get<ApiResponse>("/cameras")
    return (res.data.data as Camera[]) || []
  },
  createCamera: async (data: {
    warehouse_id: string
    camera_name: string
    stream_url: string
    status?: string
  }): Promise<Camera> => {
    const res = await client.post<ApiResponse>("/cameras", data)
    return res.data.data as Camera
  },
  updateCamera: async (id: string, data: {
    camera_name?: string
    stream_url?: string
    status?: string
  }): Promise<Camera> => {
    const res = await client.put<ApiResponse>(`/cameras/${id}`, data)
    return res.data.data as Camera
  },
  deleteCamera: async (id: string): Promise<void> => {
    await client.delete(`/cameras/${id}`)
  },

  // Inventory
  getInventory: async (): Promise<InventoryItem[]> => {
    const res = await client.get<ApiResponse>("/inventory")
    return (res.data.data as InventoryItem[]) || []
  },
  createInventoryItem: async (data: {
    product_code: string
    product_name: string
    quantity: number
    warehouse_id: string
  }): Promise<InventoryItem> => {
    const res = await client.post<ApiResponse>("/inventory", data)
    return res.data.data as InventoryItem
  },
  updateInventoryItem: async (id: string, data: {
    product_name?: string
    quantity?: number
  }): Promise<InventoryItem> => {
    const res = await client.put<ApiResponse>(`/inventory/${id}`, data)
    return res.data.data as InventoryItem
  },
  deleteInventoryItem: async (id: string): Promise<void> => {
    await client.delete(`/inventory/${id}`)
  },

  // Count logs
  getCountLogs: async (params?: {
    box_id?: string
    camera_id?: string
    movement_type?: string
  }): Promise<CountLog[]> => {
    const res = await client.get<ApiResponse>("/count-logs", { params })
    return (res.data.data as CountLog[]) || []
  },

  // Alerts
  getAlerts: async (params?: {
    alert_type?: string
    severity?: string
  }): Promise<Alert[]> => {
    const res = await client.get<ApiResponse>("/alerts", { params })
    return (res.data.data as Alert[]) || []
  },
}
