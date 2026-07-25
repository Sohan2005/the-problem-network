import * as React from "react"
import { cn } from "@/lib/utils"

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "elevated"
}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = "default", ...props }, ref) => {
    const variants = {
      default: "bg-bg-alt",
      elevated: "bg-card-bg shadow-card",
    }

    return (
      <div
        className={cn(
          "rounded-lg p-4",
          variants[variant],
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Card.displayName = "Card"

export { Card }
