import { useState } from "react";
import { CheckCircle2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/context/ToastContext";
import {
  hasOrgAiBriefContent,
  orgAiBriefWithTenantName,
  useOrgAiBrief,
  useSaveOrgAiBrief,
} from "@/hooks/useOrgAiBrief";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import type { OrgContextConfig } from "@/lib/v4RuleBookTypes";

type OrgAiBriefPanelProps = {
  tenantName?: string;
  canEdit?: boolean;
  onSaved?: () => void;
};

const ROLE_OPTIONS: Array<{
  id: OrgContextConfig["defaultPerspective"];
  label: string;
  hint: string;
}> = [
  {
    id: "buyer",
    label: "Accounts payable (buyer)",
    hint: "We receive supplier invoices and pay bills.",
  },
  {
    id: "seller",
    label: "Accounts receivable (seller)",
    hint: "We issue invoices to customers.",
  },
  {
    id: "mixed",
    label: "Both AP and AR",
    hint: "Decide purchase vs sales from party names and ABN.",
  },
];

const ROLE_LABELS: Record<OrgContextConfig["defaultPerspective"], string> = {
  buyer: "Accounts payable (buyer)",
  seller: "Accounts receivable (seller)",
  mixed: "Both AP and AR",
};

function SavedBriefSummary({ org }: { org: OrgContextConfig }) {
  return (
    <div
      className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4"
      data-testid="org-ai-brief-saved-summary"
    >
      <div className="mb-3 flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        <p className="text-sm font-medium">Saved for this organisation</p>
      </div>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Legal name</dt>
          <dd className="font-medium">{org.legalName}</dd>
        </div>
        {org.abn ? (
          <div>
            <dt className="text-xs text-muted-foreground">ABN</dt>
            <dd className="font-mono">{org.abn}</dd>
          </div>
        ) : null}
        {org.aliases.length ? (
          <div>
            <dt className="text-xs text-muted-foreground">Aliases</dt>
            <dd>{org.aliases.join(", ")}</dd>
          </div>
        ) : null}
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Role</dt>
          <dd>{ROLE_LABELS[org.defaultPerspective]}</dd>
        </div>
        {org.intakeSummary ? (
          <div className="sm:col-span-2">
            <dt className="text-xs text-muted-foreground">What you process</dt>
            <dd className="whitespace-pre-wrap text-muted-foreground">{org.intakeSummary}</dd>
          </div>
        ) : null}
        {org.classificationHints ? (
          <div className="sm:col-span-2">
            <dt className="text-xs text-muted-foreground">Classification guidance</dt>
            <dd className="whitespace-pre-wrap text-muted-foreground">{org.classificationHints}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

export function OrgAiBriefPanel({
  tenantName = "",
  canEdit = true,
  onSaved,
}: OrgAiBriefPanelProps) {
  const { toast } = useToast();
  const { data: savedOrg, isLoading, isFetching, isError, error } = useOrgAiBrief();
  const saveMutation = useSaveOrgAiBrief();
  const [draft, setDraft] = useState<OrgContextConfig | null>(null);
  const [aliasesText, setAliasesText] = useState("");
  const [dirty, setDirty] = useState(false);

  const serverOrg = orgAiBriefWithTenantName(savedOrg, tenantName);
  const form = dirty ? (draft ?? serverOrg) : serverOrg;
  const aliasesDisplay = dirty ? aliasesText : serverOrg.aliases.join(", ");
  const showSavedSummary = !dirty && !isLoading && hasOrgAiBriefContent(savedOrg);

  const beginEdit = () => {
    if (!dirty) {
      setDraft(serverOrg);
      setAliasesText(serverOrg.aliases.join(", "));
    }
  };

  const patch = (next: Partial<OrgContextConfig>) => {
    beginEdit();
    setDirty(true);
    setDraft((prev) => ({ ...(prev ?? serverOrg), ...next }));
  };

  const save = async () => {
    if (!canEdit) return;
    beginEdit();
    const base = draft ?? serverOrg;
    const aliases = aliasesText
      .split(",")
      .map((row) => row.trim())
      .filter(Boolean);
    const payload: OrgContextConfig = {
      ...base,
      legalName: base.legalName.trim(),
      abn: base.abn.trim(),
      aliases,
      intakeSummary: base.intakeSummary.trim(),
      classificationHints: base.classificationHints.trim(),
    };
    try {
      await saveMutation.mutateAsync(payload);
      setDraft(null);
      setAliasesText("");
      setDirty(false);
      onSaved?.();
      toast({ title: "AI brief saved", description: "Org context updated for this tenant." });
    } catch (err) {
      const description =
        err instanceof ApiError && err.status === 403
          ? "Only organisation admins can edit the AI brief."
          : err instanceof ApiError && err.status === 401
            ? "Your session expired. Sign in again and retry."
            : err instanceof Error
              ? err.message
              : "Request failed";
      toast({
        title: "Could not save AI brief",
        description,
        variant: "destructive",
      });
    }
  };

  return (
    <Card className="p-5 max-w-3xl" data-testid="org-ai-brief-panel">
      <div className="mb-5 flex items-start gap-3">
        <div className="rounded-md bg-primary/10 p-2 text-primary">
          <Sparkles className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground">Org AI brief</h3>
          <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
            Tell the AI who your organisation is and what documents you process. This guides
            classification alongside your Rule Book document types.
          </p>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : isError ? (
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : "Could not load org AI brief"}
        </p>
      ) : (
        <div className="space-y-5">
          {showSavedSummary ? <SavedBriefSummary org={serverOrg} /> : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="org-legal-name" className="text-sm font-medium">
                Legal name
              </label>
              <Input
                id="org-legal-name"
                value={form.legalName}
                onChange={(e) => patch({ legalName: e.target.value })}
                disabled={!canEdit}
                placeholder="Acme Manufacturing Pty Ltd"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="org-abn" className="text-sm font-medium">
                ABN
              </label>
              <Input
                id="org-abn"
                value={form.abn}
                onChange={(e) => patch({ abn: e.target.value })}
                disabled={!canEdit}
                placeholder="12 345 678 901"
                className="font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="org-aliases" className="text-sm font-medium">
                Trading names / aliases
              </label>
              <Input
                id="org-aliases"
                value={aliasesDisplay}
                onChange={(e) => {
                  beginEdit();
                  setDirty(true);
                  setAliasesText(e.target.value);
                }}
                disabled={!canEdit}
                placeholder="Acme, Acme Mfg"
              />
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Your role</p>
            <div className="grid gap-2 sm:grid-cols-3">
              {ROLE_OPTIONS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  disabled={!canEdit}
                  onClick={() => patch({ defaultPerspective: option.id })}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors",
                    form.defaultPerspective === option.id
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/30",
                    !canEdit && "opacity-60 cursor-not-allowed"
                  )}
                >
                  <span className="block text-sm font-medium">{option.label}</span>
                  <span className="mt-1 block text-[11px] text-muted-foreground">{option.hint}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="org-intake" className="text-sm font-medium">
              What you usually process
            </label>
            <textarea
              id="org-intake"
              rows={3}
              value={form.intakeSummary}
              onChange={(e) => patch({ intakeSummary: e.target.value })}
              disabled={!canEdit}
              placeholder="e.g. Supplier tax invoices, GRNs, freight dockets, bank statements. Rarely quotes or marketing PDFs."
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="org-classify-hints" className="text-sm font-medium">
              Classification guidance
            </label>
            <textarea
              id="org-classify-hints"
              rows={3}
              value={form.classificationHints}
              onChange={(e) => patch({ classificationHints: e.target.value })}
              disabled={!canEdit}
              placeholder="e.g. Prefer GRN over tax invoice when PO + delivery note. Use low confidence for letters without invoice fields."
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="flex items-center justify-end gap-3">
            {isFetching && !isLoading ? (
              <span className="text-xs text-muted-foreground">Refreshing…</span>
            ) : null}
            <Button
              type="button"
              data-testid="button-save-org-ai-brief"
              onClick={() => void save()}
              disabled={!canEdit || saveMutation.isPending || isLoading}
            >
              {saveMutation.isPending ? "Saving…" : "Save AI brief"}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
