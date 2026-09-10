import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Pencil, Plus, X } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useRuleBookDocumentTypes } from "@/hooks/useRuleBookConfig";
import { useQueryClient } from "@tanstack/react-query";
import { TEAM_EXPENSE_KIND_LABELS } from "@/lib/v4RuleBookTypes";
import { queryKeys } from "@/lib/queryClient";
import {
  defaultMobileQaFields,
  newMobileQuickActionItem,
  normalizeMobileQuickActionsSettings,
  type MobileQuickActionFieldConfig,
  type MobileQuickActionFieldsConfig,
  type MobileQuickActionItem,
  type MobileQuickActionPhotoMode,
} from "@/lib/mobileQuickActions";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { cn } from "@/lib/cn";

const CHROME_FIELD_ROWS: {
  key: keyof MobileQuickActionFieldsConfig;
  label: string;
  hint: string;
}[] = [
  { key: "parentLedger", label: "Parent ledger", hint: "From selected DT Post to" },
  { key: "adjustAdvance", label: "Adjust against advance", hint: "Yes / No" },
  { key: "spentFor", label: "Spent for", hint: "Myself / Others (+ details)" },
  { key: "remarks", label: "Remarks", hint: "Free-text notes" },
];

const PHOTO_OPTIONS = [
  { value: "compulsory", label: "Compulsory" },
  { value: "optional", label: "Optional" },
  { value: "none", label: "Hidden" },
];

function kindLabel(dt: DocumentTypeDefinition | undefined) {
  if (!dt) return "";
  const kind = (dt.teamExpenseKind || "expense_claim") as keyof typeof TEAM_EXPENSE_KIND_LABELS;
  return TEAM_EXPENSE_KIND_LABELS[kind] || kind;
}

function parentLedgerHint(dt: DocumentTypeDefinition | undefined) {
  if (!dt) return "Select a document type";
  const ledger = (dt.postTo?.ledger || "").trim();
  const sub = (dt.postTo?.subLedger || "").trim();
  if (!ledger) return "No parent ledger on this DT — set Post to in Rule Book";
  return sub ? `${ledger} → ${sub}` : ledger;
}

function sameItems(a: MobileQuickActionItem[], b: MobileQuickActionItem[]) {
  return JSON.stringify(a) === JSON.stringify(b);
}

type DraftState = {
  id?: string;
  documentTypeCode: string;
  label: string;
  allowWithDoc: boolean;
  allowWithoutDoc: boolean;
  photoRequired: MobileQuickActionPhotoMode;
  fields: MobileQuickActionFieldsConfig;
};

function emptyDraft(): DraftState {
  return {
    documentTypeCode: "",
    label: "",
    allowWithDoc: true,
    allowWithoutDoc: true,
    photoRequired: "optional",
    fields: defaultMobileQaFields(),
  };
}

type MobileQuickActionsPanelProps = {
  canEdit?: boolean;
};

export function MobileQuickActionsPanel({ canEdit = false }: MobileQuickActionsPanelProps) {
  const { data: institution, isLoading: instLoading, blocked } = useInstitutionSettings();
  const { data: documentTypes = [], isLoading: dtsLoading } = useRuleBookDocumentTypes();
  const queryClient = useQueryClient();

  const [items, setItems] = useState<MobileQuickActionItem[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<DraftState>(emptyDraft);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const isEdit = Boolean(draft.id);

  const dtByCode = useMemo(() => {
    const map = new Map<string, DocumentTypeDefinition>();
    documentTypes.forEach((dt) => map.set(dt.code.toUpperCase(), dt));
    return map;
  }, [documentTypes]);

  const selectedDt = draft.documentTypeCode
    ? dtByCode.get(draft.documentTypeCode.toUpperCase())
    : undefined;

  const pickerOptions = useMemo(() => {
    const used = new Set(
      items.filter((i) => i.id !== draft.id).map((i) => i.documentTypeCode)
    );
    return documentTypes
      .filter((dt) => {
        if (dt.enabled === false) return false;
        if (isEdit && dt.code.toUpperCase() === draft.documentTypeCode) return true;
        return !used.has(dt.code.toUpperCase());
      })
      .slice()
      .sort((a, b) => a.shortTitle.localeCompare(b.shortTitle));
  }, [documentTypes, items, draft.id, draft.documentTypeCode, isEdit]);

  useEffect(() => {
    if (!institution) return;
    setItems(normalizeMobileQuickActionsSettings(institution.mobile_quick_actions).items);
  }, [institution]);

  useEffect(() => {
    if (!modalOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeModal();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [modalOpen]);

  const savedItems = useMemo(
    () => normalizeMobileQuickActionsSettings(institution?.mobile_quick_actions).items,
    [institution]
  );
  const dirty = !sameItems(items, savedItems);

  function openCreate() {
    setDraft(emptyDraft());
    setError(null);
    setModalOpen(true);
  }

  function openEdit(item: MobileQuickActionItem) {
    setDraft({
      id: item.id,
      documentTypeCode: item.documentTypeCode,
      label: item.label,
      allowWithDoc: item.allowWithDoc,
      allowWithoutDoc: item.allowWithoutDoc,
      photoRequired: item.photoRequired,
      fields: { ...item.fields },
    });
    setError(null);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setDraft(emptyDraft());
  }

  function patchDraft(patch: Partial<DraftState>) {
    setDraft((prev) => ({ ...prev, ...patch }));
  }

  function patchDraftField(
    key: keyof MobileQuickActionFieldsConfig,
    patch: Partial<MobileQuickActionFieldConfig>
  ) {
    setDraft((prev) => ({
      ...prev,
      fields: {
        ...prev.fields,
        [key]: { ...prev.fields[key], ...patch },
      },
    }));
  }

  function onDocumentTypeChange(code: string) {
    const dt = dtByCode.get(code.toUpperCase());
    setDraft((prev) => ({
      ...prev,
      documentTypeCode: code,
      label: prev.label || dt?.shortTitle || dt?.title || "",
    }));
  }

  function commitModal() {
    if (!draft.documentTypeCode) {
      setError("Select a document type.");
      return;
    }
    const dt = dtByCode.get(draft.documentTypeCode.toUpperCase());
    if (isEdit && draft.id) {
      setItems((prev) =>
        prev.map((row) =>
          row.id === draft.id
            ? {
                ...row,
                documentTypeCode: draft.documentTypeCode.toUpperCase(),
                label: draft.label.trim() || dt?.shortTitle || dt?.title || "",
                allowWithDoc: draft.allowWithDoc,
                allowWithoutDoc: draft.allowWithoutDoc,
                photoRequired: draft.photoRequired,
                fields: draft.fields,
              }
            : row
        )
      );
    } else {
      const next = newMobileQuickActionItem(
        draft.documentTypeCode,
        draft.label.trim() || dt?.shortTitle || dt?.title || "",
        dt
      );
      next.allowWithDoc = draft.allowWithDoc;
      next.allowWithoutDoc = draft.allowWithoutDoc;
      next.photoRequired = draft.photoRequired;
      next.fields = draft.fields;
      setItems((prev) => [...prev, next]);
    }
    setSaved(false);
    setError(null);
    closeModal();
  }

  function toggleEnabled(id: string, enabled: boolean) {
    setItems((prev) => prev.map((row) => (row.id === id ? { ...row, enabled } : row)));
    setSaved(false);
    setError(null);
  }

  function removeItem(id: string) {
    setItems((prev) => prev.filter((row) => row.id !== id));
    setSaved(false);
    setError(null);
  }

  async function onSave() {
    if (!canEdit) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.updateInstitutionSettings({
        mobile_quick_actions: { items },
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.institutionSettings() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.myPermissions() });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save mobile Quick Actions.");
    } finally {
      setSaving(false);
    }
  }

  if (instLoading || dtsLoading || blocked) {
    return (
      <Card className="w-full p-6 text-sm text-muted-foreground" data-testid="mobile-qa-panel">
        Loading mobile Quick Actions…
      </Card>
    );
  }

  const modal = modalOpen
    ? createPortal(
        <div className="app-modal-root app-modal-root--blur-strong p-3 sm:p-4" role="presentation">
          <button
            type="button"
            className="app-modal-backdrop cursor-pointer"
            aria-label="Close dialog"
            onClick={closeModal}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="mobile-qa-dialog-title"
            className="app-modal-panel flex max-h-[min(560px,82vh)] max-w-md flex-col overflow-hidden bg-card p-0"
          >
            <div className="flex items-center gap-2 border-b border-border/70 px-4 py-2.5">
              <h3 id="mobile-qa-dialog-title" className="text-sm font-semibold">
                {isEdit ? "Edit Quick Action" : "Add Quick Action"}
              </h3>
              <button
                type="button"
                onClick={closeModal}
                className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3 overflow-y-auto px-4 py-3">
              <div className="grid gap-2.5 sm:grid-cols-2">
                <label className="block space-y-1">
                  <span className="text-[11px] font-medium text-muted-foreground">
                    Document type
                  </span>
                  <Select
                    value={draft.documentTypeCode}
                    disabled={!canEdit || isEdit}
                    size="sm"
                    onValueChange={onDocumentTypeChange}
                    placeholder="Select…"
                    options={pickerOptions.map((dt) => ({
                      value: dt.code,
                      label: `${dt.shortTitle || dt.title} (${dt.code})`,
                    }))}
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-[11px] font-medium text-muted-foreground">
                    Button label
                  </span>
                  <Input
                    value={draft.label}
                    maxLength={48}
                    disabled={!canEdit}
                    placeholder="e.g. Claim"
                    className="h-8 text-sm"
                    onChange={(e) => patchDraft({ label: e.target.value })}
                  />
                </label>
              </div>

              <section className="space-y-2 rounded-lg border border-border/60 px-3 py-2.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Paths
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="flex items-center justify-between gap-2 rounded-md bg-muted/30 px-2.5 py-1.5">
                    <span className="text-xs font-medium">With document</span>
                    <Switch
                      checked={draft.allowWithDoc}
                      disabled={!canEdit}
                      onCheckedChange={(allowWithDoc) => patchDraft({ allowWithDoc })}
                    />
                  </div>
                  <div className="flex items-center justify-between gap-2 rounded-md bg-muted/30 px-2.5 py-1.5">
                    <span className="text-xs font-medium">Without document</span>
                    <Switch
                      checked={draft.allowWithoutDoc}
                      disabled={!canEdit}
                      onCheckedChange={(allowWithoutDoc) => patchDraft({ allowWithoutDoc })}
                    />
                  </div>
                </div>
                <label className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-muted-foreground">Add picture</span>
                  <div className="w-[140px]">
                    <Select
                      value={draft.photoRequired}
                      disabled={!canEdit}
                      size="sm"
                      onValueChange={(value) =>
                        patchDraft({ photoRequired: value as MobileQuickActionPhotoMode })
                      }
                      options={PHOTO_OPTIONS}
                    />
                  </div>
                </label>
              </section>

              <section className="rounded-lg border border-border/60 px-3 py-2">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Quick Action fields
                </p>
                <p className="mb-2 text-[10px] text-muted-foreground">
                  Detail fields come from the document type in Rule Book. Compulsory DT fields
                  are required on mobile automatically.
                </p>
                <ul className="divide-y divide-border/50">
                  {CHROME_FIELD_ROWS.map((row) => {
                    const f = draft.fields[row.key];
                    const hint =
                      row.key === "parentLedger" ? parentLedgerHint(selectedDt) : row.hint;
                    return (
                      <li
                        key={row.key}
                        className="flex items-center justify-between gap-2 py-1.5"
                      >
                        <div className="min-w-0">
                          <span className="truncate text-xs font-medium">{row.label}</span>
                          <p className="truncate text-[10px] text-muted-foreground">{hint}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2.5">
                          <label className="flex items-center gap-1 text-[10px] text-muted-foreground">
                            <Switch
                              checked={f.visible}
                              disabled={!canEdit}
                              onCheckedChange={(visible) =>
                                patchDraftField(row.key, { visible })
                              }
                            />
                            Show
                          </label>
                          <label className="flex items-center gap-1 text-[10px] text-muted-foreground">
                            <Switch
                              checked={f.required}
                              disabled={!canEdit || !f.visible}
                              onCheckedChange={(required) =>
                                patchDraftField(row.key, { required })
                              }
                            />
                            Req.
                          </label>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border/70 px-4 py-2.5">
              {error && modalOpen ? (
                <p className="mr-auto text-xs text-destructive">{error}</p>
              ) : null}
              <Button type="button" variant="ghost" size="sm" onClick={closeModal}>
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={commitModal}
                disabled={!canEdit || !draft.documentTypeCode}
              >
                {isEdit ? "Update" : "Create"}
              </Button>
            </div>
          </div>
        </div>,
        document.body
      )
    : null;

  return (
    <div className="w-full max-w-3xl space-y-4" data-testid="mobile-qa-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Mobile Quick Actions</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Create shortcuts for document types. Toggle them on for the mobile home screen.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canEdit ? (
            <Button
              type="button"
              variant="outline"
              onClick={openCreate}
              disabled={saving || pickerOptions.length === 0}
              data-testid="mobile-qa-add"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Add
            </Button>
          ) : null}
          {canEdit ? (
            <Button
              type="button"
              onClick={() => void onSave()}
              disabled={saving || !dirty}
              data-testid="mobile-qa-save"
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          ) : null}
        </div>
      </div>

      <Card className="overflow-hidden divide-y divide-border/70">
        {!items.length ? (
          <div className="px-5 py-10 text-center text-sm text-muted-foreground">
            No Quick Actions yet. Click Add to create one.
          </div>
        ) : (
          items.map((item) => {
            const dt = dtByCode.get(item.documentTypeCode);
            const title = item.label || dt?.shortTitle || dt?.title || item.documentTypeCode;
            const ledgerHint = parentLedgerHint(dt);
            return (
              <div
                key={item.id}
                className={cn(
                  "flex items-center gap-3 px-4 py-3.5 sm:px-5",
                  !item.enabled && "opacity-60"
                )}
                data-testid={`mobile-qa-item-${item.documentTypeCode}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{title}</p>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {item.documentTypeCode}
                    {kindLabel(dt) ? ` · ${kindLabel(dt)}` : ""}
                    {ledgerHint.startsWith("No parent") || ledgerHint.startsWith("Select")
                      ? ""
                      : ` · ${ledgerHint}`}
                    {" · "}
                    {[
                      item.allowWithDoc ? "With doc" : null,
                      item.allowWithoutDoc ? "Without doc" : null,
                    ]
                      .filter(Boolean)
                      .join(" / ") || "No path"}
                  </p>
                </div>
                {canEdit ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 shrink-0 px-2 text-muted-foreground"
                    disabled={saving}
                    onClick={() => openEdit(item)}
                    aria-label={`Edit ${title}`}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                ) : null}
                {canEdit ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 shrink-0 px-2 text-muted-foreground hover:text-destructive"
                    disabled={saving}
                    onClick={() => removeItem(item.id)}
                  >
                    Remove
                  </Button>
                ) : null}
                <Switch
                  checked={item.enabled}
                  disabled={!canEdit || saving}
                  onCheckedChange={(enabled) => toggleEnabled(item.id, enabled)}
                  aria-label={`Enable ${title}`}
                />
              </div>
            );
          })
        )}
      </Card>

      <p className="text-xs text-muted-foreground">
        Approvals still appears for users with Approve or Reject privilege.
        {!canEdit ? " Only admins can edit this page." : ""}
      </p>
      {error && !modalOpen ? <p className="text-sm text-destructive">{error}</p> : null}
      {saved && !dirty ? <p className="text-sm text-emerald-700">Saved.</p> : null}

      {modal}
    </div>
  );
}
