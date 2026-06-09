import { cn } from "@/lib/cn";
import type { ButtonHTMLAttributes } from "react";

export function Switch({
  checked,
  disabled,
  onCheckedChange,
  className,
  ...props
}: {
  checked: boolean;
  disabled?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  className?: string;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange">) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onCheckedChange?.(!checked)}
      className={cn("app-switch", className)}
      {...props}
    >
      <span className="app-switch-thumb" />
    </button>
  );
}
