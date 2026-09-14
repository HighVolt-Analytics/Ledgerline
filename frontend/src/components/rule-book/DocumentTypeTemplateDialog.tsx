import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, FilePlus2, FileText, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { playbookProfileLabel } from "@/lib/documentPlaybookConfig";
import {
  DOCUMENT_TYPE_TEMPLATES,
  dictionaryIndustries,
  type DocumentTypeTemplate,
  type DocumentTypeTemplateId,
} from "@/lib/documentTypeTemplates";
import type { DocumentTypeClass } from "@/lib/v5DocumentTypes";

type DocumentTypeTemplateDialogProps = {
  open: boolean;
  onClose: () => void;
  onSelect: (templateId: DocumentTypeTemplateId) => void;
};

const DICTIONARY_TEMPLATES = DOCUMENT_TYPE_TEMPLATES.filter((row) => row.id !== "custom");
const CUSTOM_TEMPLATE = DOCUMENT_TYPE_TEMPLATES.find((row) => row.id === "custom")!;
const TOTAL_DICTIONARY_COUNT = DICTIONARY_TEMPLATES.length;

const ROUTE_TARGETS = [
  "Purchase Management",
  "Sales Management",
  "Expenses Management",
  "Team Expenses",
  "Vault",
] as const;

const KLASS_OPTIONS: Array<{ value: "all" | DocumentTypeClass; label: string }> = [
  { value: "all", label: "All classes" },
  { value: "Transactional", label: "Transactional" },
  { value: "Non-transactional", label: "Non-transactional" },
];

function postingDotClass(posting: string): string {
  const token = posting.trim().toLowerCase();
  if (token === "yes") return "bg-[hsl(var(--success))]";
  if (token === "conditional") return "bg-[hsl(var(--warning))]";
  return "bg-muted-foreground/45";
}

function postingDotTitle(posting: string): string {
  const token = posting.trim().toLowerCase();
  if (token === "yes") return "Posts to GL";
  if (token === "conditional") return "Conditional posting";
  return "Does not post to GL";
}

function TemplateRow({
  template,
  expanded,
  onToggleExpand,
  onAdopt,
}: {
  template: DocumentTypeTemplate;
  expanded: boolean;
  onToggleExpand: () => void;
  onAdopt: () => void;
}) {
  const codeLabel = template.dictionaryCode || "custom";
  const subtitleParts = [codeLabel, template.industry, template.routeTarget].filter(Boolean);

  return (
    <div className="border-b border-border last:border-b-0" data-testid={`template-${template.id}`}>
      <div className="flex items-center gap-2.5 px-3 py-2 hover:bg-muted/30 transition-colors">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
          onClick={onToggleExpand}
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span
            className={cn("h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-background", postingDotClass(template.posting))}
            title={postingDotTitle(template.posting)}
            aria-hidden
          />
          {template.id === "custom" ? (
            <FilePlus2 className="h-4 w-4 shrink-0 text-primary" />
          ) : (
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-foreground">{template.label}</span>
            <span className="block truncate text-xs text-muted-foreground">
              {subtitleParts.join(" · ")}
            </span>
          </span>
        </button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="shrink-0"
          onClick={(event) => {
            event.stopPropagation();
            onAdopt();
          }}
        >
          Use template
        </Button>
      </div>
      {expanded ? (
        <div className="space-y-2 border-t border-border bg-muted/20 px-3 py-2.5 text-xs">
          <div>
            <span className="font-medium text-foreground">Playbook</span>
            <p className="mt-0.5 text-muted-foreground">
              {playbookProfileLabel(template.playbookProfile)}
            </p>
          </div>
          {template.llmPrompt.trim() ? (
            <div>
              <span className="font-medium text-foreground">Recognition prompt</span>
              <p className="mt-0.5 leading-relaxed text-muted-foreground whitespace-pre-wrap">
                {template.llmPrompt}
              </p>
            </div>
          ) : (
            <p className="text-muted-foreground">Blank type — configure recognition in the editor.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

function DocumentTypeTemplateDialog({
  open,
  onClose,
  onSelect,
}: DocumentTypeTemplateDialogProps) {
  const [query, setQuery] = useState("");
  const [industryFilter, setIndustryFilter] = useState("all");
  const [klassFilter, setKlassFilter] = useState<"all" | DocumentTypeClass>("all");
  const [routeFilter, setRouteFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<DocumentTypeTemplateId | null>(null);

  const industries = useMemo(() => dictionaryIndustries(), []);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setIndustryFilter("all");
      setKlassFilter("all");
      setRouteFilter("all");
      setExpandedId(null);
    }
  }, [open]);

  const filteredTemplates = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return DICTIONARY_TEMPLATES.filter((template) => {
      if (industryFilter !== "all" && template.industry !== industryFilter) return false;
      if (klassFilter !== "all" && template.klass !== klassFilter) return false;
      if (routeFilter !== "all" && template.routeTarget !== routeFilter) return false;
      if (!normalized) return true;
      const haystack = [
        template.label,
        template.industry,
        template.routeTarget,
        template.dictionaryCode,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [query, industryFilter, klassFilter, routeFilter]);

  const industryOptions = useMemo(
    () => [{ value: "all", label: "All industries" }, ...toSelectOptions(industries)],
    [industries]
  );

  const routeOptions = useMemo(
    () => [
      { value: "all", label: "All routes" },
      ...ROUTE_TARGETS.map((route) => ({ value: route, label: route })),
    ],
    []
  );

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
        className="v5-dialog-content max-w-3xl p-0 gap-0 overflow-hidden flex flex-col max-h-[min(85vh,720px)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4 shrink-0">
          <div>
            <h2 id="dt-template-title" className="text-lg font-semibold tracking-tight">
              Add document type
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Pick a dictionary template to pre-fill recognition, playbook, extraction, and
              validation — then adjust in the editor before saving.
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-3 border-b border-border px-5 py-3 shrink-0">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, industry, or route…"
              className="h-9 pl-8"
              data-testid="template-search"
            />
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Select
              value={industryFilter}
              onValueChange={setIndustryFilter}
              options={industryOptions}
              placeholder="Industry"
              size="md"
              className="w-full"
              data-testid="template-filter-industry"
            />
            <Select
              value={klassFilter}
              onValueChange={(value) => setKlassFilter(value as "all" | DocumentTypeClass)}
              options={KLASS_OPTIONS.map((row) => ({ value: row.value, label: row.label }))}
              placeholder="Class"
              size="md"
              className="w-full"
              data-testid="template-filter-class"
            />
            <Select
              value={routeFilter}
              onValueChange={setRouteFilter}
              options={routeOptions}
              placeholder="Route"
              size="md"
              className="w-full"
              data-testid="template-filter-route"
            />
          </div>
        </div>

        <div className="px-5 pt-3 shrink-0">
          <p className="text-xs text-muted-foreground" data-testid="template-result-count">
            {filteredTemplates.length} of {TOTAL_DICTIONARY_COUNT} templates
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4 pt-2">
          <div className="overflow-hidden rounded-md border border-border">
            <TemplateRow
              template={CUSTOM_TEMPLATE}
              expanded={expandedId === "custom"}
              onToggleExpand={() =>
                setExpandedId((current) => (current === "custom" ? null : "custom"))
              }
              onAdopt={() => onSelect("custom")}
            />
            {filteredTemplates.length === 0 ? (
              <div className="border-t border-border px-3 py-8 text-center text-sm text-muted-foreground">
                No templates match your filters.
              </div>
            ) : (
              filteredTemplates.map((template) => (
                <TemplateRow
                  key={template.id}
                  template={template}
                  expanded={expandedId === template.id}
                  onToggleExpand={() =>
                    setExpandedId((current) => (current === template.id ? null : template.id))
                  }
                  onAdopt={() => onSelect(template.id)}
                />
              ))
            )}
          </div>
        </div>

        <div className="border-t border-border px-5 py-3 shrink-0">
          <p className="text-xs text-muted-foreground">
            Org codes are assigned automatically (DT-01, DT-02, …). Green dot = posts to GL;
            amber = conditional; gray = no posting.
          </p>
        </div>
      </div>
    </div>,
    document.body
  );
}

export { DocumentTypeTemplateDialog };
