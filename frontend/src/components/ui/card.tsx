import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function Card({ className, ...props }, ref) {
    return (
      <div
        ref={ref}
        className={cn(
          "shadcn-card rounded-xl border bg-card border-card-border text-card-foreground shadow-sm",
          className
        )}
        {...props}
      />
    );
  }
);
