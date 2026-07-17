import type { ReactNode } from "react"
import clsx from "clsx"

interface CardProps {
  children: ReactNode
  className?: string
  padding?: boolean
}

export function Card({ children, className, padding = true }: CardProps) {
  return (
    <div className={clsx("card", padding && "p-4 sm:p-6", className)}>
      {children}
    </div>
  )
}
