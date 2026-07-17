"use client"

import { useState, useEffect, useCallback } from "react"
import { api } from "@/lib/api"
import type { InventoryItem, CountLog, Warehouse } from "@/lib/types"
import { Card } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Modal } from "@/components/ui/Modal"
import { Badge } from "@/components/ui/Badge"
import { Spinner } from "@/components/ui/Spinner"
import { format } from "date-fns"
import clsx from "clsx"

type Tab = "products" | "movements"

export default function InventoryPage() {
  const [tab, setTab] = useState<Tab>("products")
  const [items, setItems] = useState<InventoryItem[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [movements, setMovements] = useState<CountLog[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<InventoryItem | null>(null)
  const [productCode, setProductCode] = useState("")
  const [productName, setProductName] = useState("")
  const [quantity, setQuantity] = useState(0)
  const [whId, setWhId] = useState("")
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    try {
      const [inv, whs] = await Promise.all([
        api.getInventory(),
        api.getWarehouses(),
      ])
      setItems(inv)
      setWarehouses(whs)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetch() }, [fetch])

  async function fetchMovements() {
    try {
      const logs = await api.getCountLogs()
      setMovements(logs.slice(0, 200))
    } catch {
      // silent
    }
  }

  useEffect(() => {
    if (tab === "movements") fetchMovements()
  }, [tab])

  function openCreate() {
    setEditing(null)
    setProductCode("")
    setProductName("")
    setQuantity(0)
    setWhId(warehouses[0]?.id || "")
    setModalOpen(true)
  }

  function openEdit(item: InventoryItem) {
    setEditing(item)
    setProductCode(item.product_code)
    setProductName(item.product_name)
    setQuantity(item.quantity)
    setWhId(item.warehouse_id)
    setModalOpen(true)
  }

  async function handleSave() {
    if (!productCode.trim() || !productName.trim()) return
    setSaving(true)
    try {
      if (editing) {
        await api.updateInventoryItem(editing.id, {
          product_name: productName,
          quantity,
        })
      } else {
        await api.createInventoryItem({
          product_code: productCode,
          product_name: productName,
          quantity,
          warehouse_id: whId,
        })
      }
      setModalOpen(false)
      await fetch()
    } catch {
      // silent
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    await api.deleteInventoryItem(id)
    setConfirmDelete(null)
    await fetch()
  }

  function getWarehouseName(id: string) {
    return warehouses.find((w) => w.id === id)?.name || id
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="text-left">
          <h2 className="text-2xl font-extrabold text-slate-900 tracking-tight">CRAX Product Batches</h2>
          <p className="text-sm text-slate-500 mt-1">Track packaging flavors and conveyor scan logs</p>
        </div>
        <Button onClick={openCreate} className="rounded-full shadow-md shadow-blue-500/10">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
          </svg>
          Register Flavor Batch
        </Button>
      </div>

      <div className="flex gap-1 p-1 bg-gray-100 rounded-lg w-fit">
        {(["products", "movements"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              "px-4 py-2 text-sm font-semibold rounded-md transition-all whitespace-nowrap",
              tab === t ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800",
            )}
          >
            {t === "products" ? "Flavor Catalog" : "Carton Scan Logs"}
          </button>
        ))}
      </div>

      {tab === "products" && (
        <>
          {items.length === 0 ? (
            <Card>
              <div className="text-center py-12 text-slate-500">
                <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                </svg>
                <p className="font-semibold">No flavor batches registered</p>
                <p className="text-sm mt-1">Add a product flavor to begin conveyor scanning tracking</p>
              </div>
            </Card>
          ) : (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto select-text">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50/50">
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Batch Code</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Flavor / Product Name</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-slate-400 uppercase tracking-wider">Cases Processed</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Warehouse Line</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-slate-400 uppercase tracking-wider">Last Scan</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-slate-400 uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-medium text-slate-700">
                    {items.map((item) => (
                      <tr key={item.id} className="hover:bg-slate-50/50 transition-colors">
                        <td className="px-4 py-3">
                          <code className="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono font-bold text-slate-900">
                            {item.product_code}
                          </code>
                        </td>
                        <td className="px-4 py-3 font-bold text-slate-900">{item.product_name}</td>
                        <td className="px-4 py-3 text-right">
                          <Badge variant={item.quantity > 10 ? "success" : item.quantity > 0 ? "warning" : "danger"}>
                            {item.quantity} cases
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{getWarehouseName(item.warehouse_id)}</td>
                        <td className="px-4 py-3 text-right text-slate-500 text-xs">
                          {format(new Date(item.updated_at), "MMM d, HH:mm")}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            <Button variant="secondary" size="sm" onClick={() => openEdit(item)}>Edit</Button>
                            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(item.id)}>Delete</Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 bg-slate-50/30 border-t border-slate-100 text-xs font-bold text-slate-400 uppercase tracking-wide">
                {items.length} flavor{items.length !== 1 ? "s" : ""} cataloged
              </div>
            </div>
          )}
        </>
      )}

      {tab === "movements" && (
        <>
          {movements.length === 0 ? (
            <Card>
              <div className="text-center py-12 text-slate-500">
                <p className="font-semibold">No carton scans logged</p>
                <p className="text-sm mt-1">Conveyor logs will populate here once live cameras detect carton boxes</p>
              </div>
            </Card>
          ) : (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto select-text">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50/50">
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Timestamp</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Carton ID</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Conveyor Camera</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Scan Event</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-medium text-slate-700">
                    {movements.map((log) => (
                      <tr key={log.id} className="hover:bg-slate-50/50 transition-colors">
                        <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                          {format(new Date(log.timestamp), "MMM d, yyyy HH:mm:ss")}
                        </td>
                        <td className="px-4 py-3">
                          <code className="text-xs font-mono text-slate-900 font-bold">#CRAX-{log.box_id.slice(0, 8).toUpperCase()}</code>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{log.camera_id}</td>
                        <td className="px-4 py-3">
                          <Badge variant={log.movement_type === "ENTRY" ? "success" : "warning"}>
                            {log.movement_type === "ENTRY" ? "DISPATCH" : "INGRESS"}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 bg-slate-50/30 border-t border-slate-100 text-xs font-bold text-slate-400 uppercase tracking-wide">
                {movements.length} carton scan{movements.length !== 1 ? "s" : ""} logged
              </div>
            </div>
          )}
        </>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? "Modify Flavor Batch" : "Register Flavor Batch"}>
        <form onSubmit={(e) => { e.preventDefault(); handleSave() }} className="space-y-4 text-left">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Batch Code</label>
            <input
              value={productCode}
              onChange={(e) => setProductCode(e.target.value)}
              className="input-field font-mono font-bold"
              placeholder="e.g. CRAX-MASALA-24G"
              required
              disabled={!!editing}
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Flavor / Product Name</label>
            <input
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              className="input-field"
              placeholder="e.g. Masala Rings"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Cases Processed</label>
            <input
              type="number"
              min={0}
              value={quantity}
              onChange={(e) => setQuantity(Number(e.target.value))}
              className="input-field"
            />
          </div>
          {!editing && (
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Warehouse Location</label>
              <select
                value={whId}
                onChange={(e) => setWhId(e.target.value)}
                className="input-field text-slate-800"
                required
              >
                <option value="" className="text-slate-400">Select plant line</option>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)} className="rounded-full">Cancel</Button>
            <Button type="submit" loading={saving} className="rounded-full">{editing ? "Save Changes" : "Register Batch"}</Button>
          </div>
        </form>
      </Modal>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete Flavor Batch" size="sm">
        <p className="text-sm text-slate-500 text-left">Are you sure you want to remove this flavor batch from the tracking register?</p>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)} className="rounded-full">Cancel</Button>
          <Button variant="danger" onClick={() => confirmDelete && handleDelete(confirmDelete)} className="rounded-full">Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
