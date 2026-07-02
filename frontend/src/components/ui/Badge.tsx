import clsx from "clsx"

export function Badge({
  variant = "default",
  children,
}: {
  variant?: "default" | "success" | "warning" | "danger" | "info"
  children: React.ReactNode
}) {
  const variants: Record<string, string> = {
    default: "bg-gray-100 text-gray-700",
    success: "bg-success-light text-success",
    warning: "bg-warning-light text-warning",
    danger: "bg-danger-light text-danger",
    info: "bg-info-light text-info",
  }

  return <span className={clsx("badge", variants[variant])}>{children}</span>
}
