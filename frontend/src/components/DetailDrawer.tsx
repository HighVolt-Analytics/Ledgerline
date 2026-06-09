import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

export function DetailDrawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: string;
  children: ReactNode;
  size?: "md" | "lg";
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" className="invoice-drawer-backdrop" aria-label="Close" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "invoice-drawer-panel flex h-full flex-col border-l border-border bg-background shadow-lg overflow-y-auto",
          size === "lg" ? "w-full sm:max-w-2xl" : "w-full sm:max-w-md"
        )}
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
          <div>
            <h2 className="text-base font-semibold">{title}</h2>
            {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-sm opacity-70 hover:opacity-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 p-5">{children}</div>
      </div>
    </div>
  );
}
