import type { LucideIcon } from "lucide-react";
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
  title,
  onClick,
  testId,
  className,
  iconClassName,
  static: isStatic,
}: ActionChipProps) {
  const toneClass =
    tone === "reprocess" ? "approvals-action-chip--kpi-rust" : `approvals-action-chip--${tone}`;

  return (
    <button
      type="button"
      className={cn(
        "approvals-action-chip",
        toneClass,
        variant === "outline" && "approvals-action-chip--outline",
        isStatic && "approvals-action-chip--static",
        className
      )}
      disabled={disabled}
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      data-testid={testId}
    >
      <Icon className={cn("approvals-action-chip__icon", iconClassName)} />
      {label}
    </button>
  );
}
