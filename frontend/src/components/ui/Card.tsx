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

export function StatCard({
  label,
  value,
  icon,
  trend,
  color = "primary",
}: {
  label: string
  value: string | number
  icon: ReactNode
  trend?: { value: string; positive: boolean }
  color?: "primary" | "success" | "warning" | "danger" | "info"
}) {
  const colorMap: Record<string, string> = {
    primary: "bg-primary-light text-primary",
    success: "bg-success-light text-success",
    warning: "bg-warning-light text-warning",
    danger: "bg-danger-light text-danger",
    info: "bg-info-light text-info",
  }

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-secondary">{label}</p>
          <p className="mt-1 text-2xl sm:text-3xl font-bold text-foreground">{value}</p>
          {trend && (
            <p className={clsx("mt-1 text-xs font-medium", trend.positive ? "text-success" : "text-danger")}>
              {trend.value}
            </p>
          )}
        </div>
        <div className={clsx("p-3 rounded-lg shrink-0", colorMap[color])}>
          {icon}
        </div>
      </div>
    </Card>
  )
}
