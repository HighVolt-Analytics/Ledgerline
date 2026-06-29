import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { FileText, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import {
  DOCUMENT_TYPE_TEMPLATES,
  type DocumentTypeTemplate,
  type DocumentTypeTemplateId,
} from "@/lib/documentTypeTemplates";
import type { DocumentTypeClass } from "@/lib/v5DocumentTypes";

type DocumentTypeTemplateDialogProps = {
  open: boolean;
  onClose: () => void;
  onSelect: (templateId: DocumentTypeTemplateId) => void;
};

const KLASS_FILTERS: Array<{ value: "all" | DocumentTypeClass; label: string }> = [
  { value: "all", label: "All" },
  { value: "Transactional", label: "Transactional" },
  { value: "Supporting", label: "Supporting" },
  { value: "Pre-transactional", label: "Pre-transactional" },
  { value: "Reconciliation", label: "Reconciliation" },
  { value: "Informational", label: "Informational" },
  { value: "Master-data", label: "Master data" },
  { value: "Non-actionable", label: "Non-actionable" },
  { value: "Compliance", label: "Compliance" },
];

function TemplateCard({
  template,
  onSelect,
}: {
  template: DocumentTypeTemplate;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex flex-col rounded-xl border border-border bg-card p-4 text-left transition",
        "hover:-translate-y-px hover:border-primary/40 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
      data-testid={`template-${template.id}`}
    >
      <div className="flex items-start gap-2">
        <FileText className="h-4 w-4 shrink-0 text-primary mt-0.5" />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground">{template.label}</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{template.description}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground">
          {template.routeTarget}
        </span>
        <span className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground">
          {template.klass}
        </span>
        <span className="rounded-full border border-primary/20 bg-primary/5 px-2 py-0.5 text-[10px] text-primary">
          Match rules
        </span>
      </div>
    </button>
  );
}

export function DocumentTypeTemplateDialog({
  open,
  onClose,
  onSelect,
}: DocumentTypeTemplateDialogProps) {
  const [query, setQuery] = useState("");
  const [klassFilter, setKlassFilter] = useState<"all" | DocumentTypeClass>("all");

  const templates = useMemo(() => {
    const base = DOCUMENT_TYPE_TEMPLATES.filter((template) => template.id !== "custom");
    const normalized = query.trim().toLowerCase();
    return base.filter((template) => {
      if (klassFilter !== "all" && template.klass !== klassFilter) return false;
      if (!normalized) return true;
      const haystack = [template.label, template.description, template.routeTarget, template.klass]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [query, klassFilter]);

  if (!open) return null;

  return createPortal(
    <div className="v5-dialog-root" role="presentation">
      <button
        type="button"
        className="v5-dialog-overlay"
        aria-label="Close template picker"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dt-template-title"
        className="v5-dialog-content max-w-4xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h2 id="dt-template-title" className="text-lg font-semibold tracking-tight">
              Add document type
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Pick a shipped template to pre-fill playbook, extraction, and match rules — then
              adjust in the editor before saving.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm p-1 opacity-70 hover:opacity-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 border-b border-border px-5 py-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or route…"
              className="pl-8 h-9"
              data-testid="template-search"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {KLASS_FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setKlassFilter(option.value)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] transition",
                  klassFilter === option.value
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/40"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-3 p-5 sm:grid-cols-2 max-h-[min(65vh,560px)] overflow-y-auto">
          {templates.length === 0 ? (
            <p className="col-span-full py-8 text-center text-sm text-muted-foreground">
              No templates match your search.
            </p>
          ) : (
            templates.map((template) => (
              <TemplateCard
                key={template.id}
                template={template}
                onSelect={() => onSelect(template.id)}
              />
            ))
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
          <p className="text-xs text-muted-foreground">
            Org codes are assigned automatically (DT-01, DT-02, …).
          </p>
          <Button type="button" size="sm" variant="ghost" onClick={() => onSelect("custom")}>
            Blank type (match rules)
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
