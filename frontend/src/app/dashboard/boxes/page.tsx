"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export default function BoxesPage() {
  const router = useRouter()
  useEffect(() => {
    router.replace("/dashboard")
  }, [router])
  return null
}
