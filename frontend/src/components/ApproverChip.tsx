import { Check, Clock, X } from "lucide-react";
import { cn } from "@/lib/cn";

export function ApproverChip({
  name,
  role,
  state,
  disabled,
  disabledTitle,
}: {
  name: string;
  role: string;
  state: string;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  const tone =
    state === "approved"
      ? "border-primary/40 text-primary bg-primary/5"
      : state === "rejected"
        ? "border-destructive/40 text-destructive bg-destructive/5"
        : "border-border text-muted-foreground bg-muted/40";
  const Icon = state === "approved" ? Check : state === "rejected" ? X : Clock;

  return (
    <span
      title={disabled ? disabledTitle : role}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        tone,
        disabled && "opacity-50"
      )}
    >
      <Icon className="h-3 w-3" />
      <span>{name}</span>
      <span className="opacity-60">·</span>
      <span className="opacity-70">{role}</span>
    </span>
  );
}
