import type { ButtonHTMLAttributes, ReactNode } from "react"
import clsx from "clsx"

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost"
  size?: "sm" | "md"
  loading?: boolean
  children: ReactNode
}

export function Button({
  variant = "primary",
  size = "md",
  loading,
  children,
  className,
  disabled,
  ...props
}: ButtonProps) {
  const variants = {
    primary: "btn-primary",
    secondary: "btn-secondary",
    danger: "btn-danger",
    ghost: "inline-flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg text-secondary hover:text-foreground hover:bg-gray-100 transition-all",
  }
  const sizes = {
    sm: "px-3 py-1.5 text-xs",
    md: "",
  }

  return (
    <button
      className={clsx(variants[variant], sizes[size], loading && "opacity-70 cursor-wait", className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin -ml-1 h-4 w-4" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}
