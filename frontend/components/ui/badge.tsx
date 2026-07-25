import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "success" | "warning" | "error"
}

const Badge = React.forwardRef<HTMLDivElement, BadgeProps>(
  ({ className, variant = "default", ...props }, ref) => {
    const variants = {
      default: "bg-bg-alt text-text border border-border",
      success: "bg-success text-white",
      warning: "bg-warning text-white",
      error: "bg-error text-white",
    }

    return (
      <div
        className={cn(
          "inline-flex items-center rounded-md px-2 py-1 text-xs font-medium",
          variants[variant],
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Badge.displayName = "Badge"

export { Badge }
