import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

const PANEL_CLASS: Record<"md" | "lg" | "purchase", string> = {
  md: "invoice-drawer-panel--sheet",
  purchase: "invoice-drawer-panel--purchase",
  lg: "",
};

export function DetailDrawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  size = "md",
  testId,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: string;
  children: ReactNode;
  size?: "md" | "lg" | "purchase";
  testId?: string;
}) {
  const [mounted, setMounted] = useState(false);
  const [sheetState, setSheetState] = useState<"open" | "closed">("closed");

  useEffect(() => {
    if (open) {
      setMounted(true);
      setSheetState("closed");
      const timer = window.setTimeout(() => setSheetState("open"), 16);
      return () => window.clearTimeout(timer);
    }
    setSheetState("closed");
    const timer = window.setTimeout(() => setMounted(false), 300);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mounted, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div className="pointer-events-none" data-testid={testId}>
      <button
        type="button"
        data-state={sheetState}
        className="invoice-drawer-backdrop pointer-events-auto"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        data-state={sheetState}
        className={cn(
          "invoice-drawer-panel pointer-events-auto flex h-full flex-col gap-0 border-l border-border bg-card p-0 shadow-lg",
          PANEL_CLASS[size]
        )}
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
          <div className="min-w-0 pr-4">
            <h2 className="text-base font-semibold">{title}</h2>
            {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-sm opacity-70 hover:opacity-100 shrink-0">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>,
    document.body
  );
}
