import type { LucideIcon } from "lucide-react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export type ActionChipTone =
  | "edit"
  | "approve"
  | "reject"
  | "delete"
  | "pending"
  | "post"
  | "review"
  | "reprocess";

type ActionChipProps = {
  tone: ActionChipTone;
  icon: LucideIcon;
  label: string;
  variant?: "filled" | "outline";
  disabled?: boolean;
  busy?: boolean;
  /** Hide the text label (keep aria-label / title). */
  iconOnly?: boolean;
  title?: string;
  onClick?: () => void;
  testId?: string;
  className?: string;
  iconClassName?: string;
  static?: boolean;
};

export function ActionChip({
  tone,
  icon: Icon,
  label,
  variant = "filled",
  disabled,
  busy,
  iconOnly,
  title,
  onClick,
  testId,
  className,
  iconClassName,
  static: isStatic,
}: ActionChipProps) {
  const toneClass =
    tone === "reprocess" ? "approvals-action-chip--kpi-rust" : `approvals-action-chip--${tone}`;
  const tip = title ?? label;

  return (
    <button
      type="button"
      className={cn(
        "approvals-action-chip",
        toneClass,
        variant === "outline" && "approvals-action-chip--outline",
        isStatic && "approvals-action-chip--static",
        iconOnly && "approvals-action-chip--icon-only px-1.5",
        className
      )}
      disabled={disabled || busy}
      title={tip}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        if (busy) return;
        onClick?.();
      }}
      data-testid={testId}
    >
      {busy ? (
        <Loader2 className={cn("approvals-action-chip__icon animate-spin", iconClassName)} />
      ) : (
        <Icon className={cn("approvals-action-chip__icon", iconClassName)} />
      )}
      {iconOnly ? null : busy ? "…" : label}
    </button>
  );
}
