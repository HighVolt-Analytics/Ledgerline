import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search, Settings2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { MatchRuleFieldSelect } from "@/components/rule-book/MatchRuleFieldSelect";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import type { ConditionOperator } from "@/lib/v4RuleBookTypes";
import {
  BOOLEAN_OPERATORS,
  compileMatchRulesToClassifier,
  CUSTOM_MATCH_RULE_FIELD,
  documentTypeWithMatchRulesForm,
  emptyMatchRulesForm,
  hasActionableMatchRules,
  hasCompilableMatchRules,
  isMatchRuleBooleanField,
  matchRuleFieldGroupsForDocumentType,
  matchRulesFormFromClassifier,
  parseClassifierToMatchRules,
  TEXT_OPERATORS,
  type MatchRuleMode,
  type MatchRuleRow,
  type MatchRulesForm,
} from "@/lib/documentMatchRules";
import {
  applyRecognitionSignals,
  applyUserRecognitionMode,
  inferUserRecognitionMode,
  recognitionSignalChoices,
  selectedRecognitionSignals,
  USER_RECOGNITION_MODES,
  type UserRecognitionMode,
} from "@/lib/documentUserRecognition";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import type { RecognitionSignalId } from "@/lib/documentClassifierBuilder";

type DocumentMatchRulesEditorProps = {
  draft: DocumentTypeDefinition;
  onChange: (next: DocumentTypeDefinition) => void;
  onOpenAdvanced: () => void;
  onFormChange?: (form: MatchRulesForm) => void;
  /** Custom types: strict match/exclude rules only (no AI description tab). */
  rulesOnly?: boolean;
};

function defaultTextRule(): MatchRuleRow {
  return { field: "document_heading", operator: "contains", value: "" };
}

function defaultExcludeRule(): MatchRuleRow {
  return { field: "document_heading", operator: "contains", value: "" };
}

function RuleRowEditor({
  row,
  onChange,
  onRemove,
  fieldGroups,
}: {
  row: MatchRuleRow;
  onChange: (next: MatchRuleRow) => void;
  onRemove: () => void;
  fieldGroups: ReturnType<typeof matchRuleFieldGroupsForDocumentType>;
}) {
  const catalogKeys = useMemo(
    () => new Set(fieldGroups.flatMap((group) => group.fields.map((field) => field.key))),
    [fieldGroups]
  );
  const [customKeyMode, setCustomKeyMode] = useState(
    () => row.field !== "" && !catalogKeys.has(row.field)
  );
  const useCustomInput = customKeyMode || (row.field !== "" && !catalogKeys.has(row.field));
  const isBoolean = isMatchRuleBooleanField(row.field);
  const operators = isBoolean ? BOOLEAN_OPERATORS : TEXT_OPERATORS;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {useCustomInput ? (
        <>
          <input
            value={row.field}
            onChange={(e) =>
              onChange({
                ...row,
                field: e.target.value.trim().toLowerCase().replace(/\s+/g, "_"),
                operator: isMatchRuleBooleanField(e.target.value) ? "equals" : row.operator,
              })
            }
            placeholder="custom_field_name"
            className="h-8 min-w-[180px] rounded-md border border-input bg-background px-2 text-xs font-mono"
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-[11px]"
            onClick={() => {
              setCustomKeyMode(false);
              onChange({ field: "document_heading", operator: "contains", value: "" });
            }}
          >
            Preset fields
          </Button>
        </>
      ) : (
        <MatchRuleFieldSelect
          value={row.field}
          groups={fieldGroups}
          onValueChange={(field) => {
            if (field === CUSTOM_MATCH_RULE_FIELD) {
              setCustomKeyMode(true);
              onChange({ field: "", operator: "contains", value: "" });
              return;
            }
            onChange(
              isMatchRuleBooleanField(field)
                ? { field, operator: "equals", value: "true" }
                : { ...row, field, operator: "contains" }
            );
          }}
          className="h-8 min-w-[180px]"
        />
      )}
      {!isBoolean ? (
        <Select
          value={row.operator}
          onValueChange={(operator) =>
            onChange({ ...row, operator: operator as ConditionOperator })
          }
          options={operators.map((o) => ({ value: o.key, label: o.label }))}
          className="h-8 min-w-[120px] text-xs"
        />
      ) : null}
      {!isBoolean ? (
        <input
          value={row.value}
          onChange={(e) => onChange({ ...row, value: e.target.value })}
          placeholder="value"
          className="h-8 min-w-[140px] flex-1 rounded-md border border-input bg-background px-2 text-xs font-mono"
        />
      ) : (
        <Select
          value={row.value === "false" ? "false" : "true"}
          onValueChange={(value) => onChange({ ...row, value })}
          options={[
            { value: "true", label: "Yes / true" },
            { value: "false", label: "No / false" },
          ]}
          className="h-8 min-w-[100px] text-xs"
        />
      )}
      <Button type="button" size="icon" variant="ghost" className="h-8 w-8" onClick={onRemove}>
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function RuleSection({
  title,
  hint,
  mode,
  onModeChange,
  rules,
  onRulesChange,
  onAdd,
  fieldGroups,
}: {
  title: string;
  hint: string;
  mode: MatchRuleMode;
  onModeChange: (mode: MatchRuleMode) => void;
  rules: MatchRuleRow[];
  onRulesChange: (rules: MatchRuleRow[]) => void;
  onAdd: () => void;
  fieldGroups: ReturnType<typeof matchRuleFieldGroupsForDocumentType>;
}) {
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-foreground">{title}</p>
          <p className="text-[11px] text-muted-foreground">{hint}</p>
        </div>
        <div className="flex rounded-md border border-border p-0.5 text-[11px]">
          <button
            type="button"
            className={cn(
              "rounded px-2 py-0.5",
              mode === "any" ? "bg-primary/15 text-primary" : "text-muted-foreground"
            )}
            onClick={() => onModeChange("any")}
          >
            Any (OR)
          </button>
          <button
            type="button"
            className={cn(
              "rounded px-2 py-0.5",
              mode === "all" ? "bg-primary/15 text-primary" : "text-muted-foreground"
            )}
            onClick={() => onModeChange("all")}
          >
            All (AND)
          </button>
        </div>
      </div>
      <div className="space-y-2">
        {rules.map((row, index) => (
          <RuleRowEditor
            key={`${row.field}-${index}`}
            row={row}
            fieldGroups={fieldGroups}
            onChange={(next) => {
              const copy = [...rules];
              copy[index] = next;
              onRulesChange(copy);
            }}
            onRemove={() => onRulesChange(rules.filter((_, i) => i !== index))}
          />
        ))}
      </div>
      <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={onAdd}>
        <Plus className="h-3 w-3 mr-1" />
        Add rule
      </Button>
    </div>
  );
}

function RecognitionSignalsPanel({
  draft,
  onChange,
}: {
  draft: DocumentTypeDefinition;
  onChange: (next: DocumentTypeDefinition) => void;
}) {
  const [query, setQuery] = useState("");
  const options = useMemo(() => recognitionSignalChoices(), []);
  const selected = useMemo(() => new Set(selectedRecognitionSignals(draft)), [draft]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (row) =>
        row.label.toLowerCase().includes(q) ||
        row.hint.toLowerCase().includes(q) ||
        row.channel.toLowerCase().includes(q)
    );
  }, [options, query]);

  const byChannel = useMemo(() => {
    const map = new Map<string, typeof options>();
    for (const row of filtered) {
      const key = row.channel || "General";
      const list = map.get(key) ?? [];
      list.push(row);
      map.set(key, list);
    }
    return [...map.entries()];
  }, [filtered]);

  const toggle = (signalId: RecognitionSignalId, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(signalId);
    else next.delete(signalId);
    onChange(applyRecognitionSignals(draft, [...next]));
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Tick every pattern that usually appears on this document. A match on{" "}
        <strong>any</strong> ticked signal can classify it (grouped by document family).
      </p>
      <div className="relative">
        <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search signals — invoice, quote, bank, GRN…"
          className="h-8 w-full rounded-md border border-input bg-background pl-8 pr-2 text-xs"
        />
      </div>
      {options.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Signal catalogue is loading. Save and refresh, or use AI description / match rules.
        </p>
      ) : (
        <div className="max-h-64 space-y-3 overflow-y-auto rounded-md border border-border bg-muted/20 p-3">
          {byChannel.map(([channel, rows]) => (
            <div key={channel}>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {channel}
              </p>
              <ul className="space-y-2">
                {rows.map((signal) => {
                  const checked = selected.has(signal.id);
                  return (
                    <li key={signal.id}>
                      <label className="flex cursor-pointer items-start gap-2.5">
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4 rounded border-input"
                          checked={checked}
                          onChange={(e) => toggle(signal.id, e.target.checked)}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm text-foreground">{signal.label}</span>
                          {signal.hint ? (
                            <span className="block text-xs text-muted-foreground">{signal.hint}</span>
                          ) : null}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MatchRulesPanel({
  draft,
  onChange,
  onFormChange,
}: {
  draft: DocumentTypeDefinition;
  onChange: (next: DocumentTypeDefinition) => void;
  onFormChange?: (form: MatchRulesForm) => void;
}) {
  const [form, setForm] = useState<MatchRulesForm>(() =>
    matchRulesFormFromClassifier(draft.classifier.root)
  );

  useEffect(() => {
    const initial = matchRulesFormFromClassifier(draft.classifier.root);
    setForm(initial);
    onFormChange?.(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when switching types
  }, [draft.code]);

  const applyForm = useCallback(
    (nextForm: MatchRulesForm) => {
      setForm(nextForm);
      onFormChange?.(nextForm);
      onChange(documentTypeWithMatchRulesForm(draft, nextForm));
    },
    [draft, onChange, onFormChange]
  );

  const fieldGroups = useMemo(
    () => matchRuleFieldGroupsForDocumentType(draft.extractionFields),
    [draft.extractionFields]
  );
  const rulesIncomplete =
    hasActionableMatchRules(form) && !hasCompilableMatchRules(form);
  const treeParseable = useMemo(
    () => parseClassifierToMatchRules(draft.classifier.root).parseable,
    [draft.classifier.root]
  );

  return (
    <div className="space-y-4">
      {rulesIncomplete ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Each text rule needs a value (e.g. <strong>tax invoice</strong> in the heading field)
          before save will work.
        </p>
      ) : null}
      {!treeParseable ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          This type uses an advanced condition tree. Saving simple rules here will replace that tree.
        </p>
      ) : null}

      <p className="text-[11px] text-muted-foreground">
        Combine OCR text, extracted amounts/dates, email channel, and automatic checks. Add custom
        extraction fields under Processing → Fields to use them here as match rules.
      </p>

      <RuleSection
        title="Match when"
        hint={
          form.matchMode === "any"
            ? "Any one rule is enough to match."
            : "Every rule must match."
        }
        mode={form.matchMode}
        onModeChange={(matchMode) => applyForm({ ...form, matchMode })}
        rules={form.matchRules}
        onRulesChange={(matchRules) => applyForm({ ...form, matchRules })}
        onAdd={() => applyForm({ ...form, matchRules: [...form.matchRules, defaultTextRule()] })}
        fieldGroups={fieldGroups}
      />

      <RuleSection
        title="Do not match if (optional)"
        hint={
          form.excludeMode === "any"
            ? "Exclude when any rule matches."
            : "Exclude only when all rules match."
        }
        mode={form.excludeMode}
        onModeChange={(excludeMode) => applyForm({ ...form, excludeMode })}
        rules={form.excludeRules}
        onRulesChange={(excludeRules) => applyForm({ ...form, excludeRules })}
        onAdd={() =>
          applyForm({ ...form, excludeRules: [...form.excludeRules, defaultExcludeRule()] })
        }
        fieldGroups={fieldGroups}
      />
    </div>
  );
}

export function DocumentMatchRulesEditor({
  draft,
  onChange,
  onOpenAdvanced,
  onFormChange,
  rulesOnly = false,
}: DocumentMatchRulesEditorProps) {
  const mode = useMemo(() => inferUserRecognitionMode(draft), [draft]);
  const [activeMode, setActiveMode] = useState<UserRecognitionMode>(rulesOnly ? "rules" : mode);

  useEffect(() => {
    setActiveMode(rulesOnly ? "rules" : mode);
  }, [mode, rulesOnly]);

  const setCatalogueEnabled = (enabled: boolean) => {
    onChange({ ...draft, enabled });
  };

  const switchMode = (nextMode: UserRecognitionMode) => {
    setActiveMode(nextMode);
    onChange(applyUserRecognitionMode(draft, nextMode));
  };

  return (
    <div className="space-y-4" data-testid="document-match-rules-editor">
      <div className="flex items-center gap-2">
        <Switch id="dt-ai-enabled" checked={draft.enabled} onCheckedChange={setCatalogueEnabled} />
        <label htmlFor="dt-ai-enabled" className="text-sm text-foreground cursor-pointer">
          {rulesOnly ? "Include in document type catalogue" : "Include in AI classification catalogue"}
        </label>
      </div>

      {rulesOnly ? (
        <p className="text-xs text-muted-foreground">
          Recognition uses strict match and exclude rules on OCR fields after upload. Adjust rules
          below — AI description is not used for this type.
        </p>
      ) : null}

      {!rulesOnly ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-foreground">How should we recognise this type?</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {USER_RECOGNITION_MODES.map((option) => (
              <button
                key={option.id}
                type="button"
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors",
                  activeMode === option.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/30"
                )}
                onClick={() => switchMode(option.id)}
              >
                <span className="block text-sm font-medium text-foreground">{option.label}</span>
                <span className="mt-1 block text-[11px] leading-snug text-muted-foreground">
                  {option.hint}
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {!rulesOnly && activeMode === "ai" ? (
        <div className="space-y-3 rounded-md border border-border bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">
            Write a clear description in <strong>How to recognise this document</strong> above.
            The AI uses that summary (plus the optional hint below) when choosing a type. No OCR
            match rules are required — best for distinctive layouts, letter types, or internal forms.
          </p>
          <div className="space-y-1.5">
            <label htmlFor="dt-llm-hint" className="text-xs font-medium text-foreground">
              Extra AI hint (optional)
            </label>
            <textarea
              id="dt-llm-hint"
              rows={2}
              value={draft.llmHint ?? ""}
              onChange={(e) => onChange({ ...draft, llmHint: e.target.value })}
              placeholder="e.g. Often a PDF letterhead; may say ‘statement of account’ not ‘invoice’"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Need stricter checks after OCR? Switch to <strong>Document signals</strong> or{" "}
            <strong>Match / exclude rules</strong>.
          </p>
        </div>
      ) : null}

      {!rulesOnly && activeMode === "signals" ? (
        <RecognitionSignalsPanel draft={draft} onChange={onChange} />
      ) : null}

      {rulesOnly || activeMode === "rules" ? (
        <MatchRulesPanel draft={draft} onChange={onChange} onFormChange={onFormChange} />
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">
          {rulesOnly || activeMode === "rules"
            ? "Rules verify OCR after classification."
            : activeMode === "signals"
              ? "Signals compile to grouped OR conditions for AI hints and pipeline checks."
              : "AI description is optional. Switch to Match / exclude rules for strict checks."}
        </p>
        <Button type="button" size="sm" variant="outline" className="h-8" onClick={onOpenAdvanced}>
          <Settings2 className="h-3.5 w-3.5 mr-1" />
          Advanced condition tree
        </Button>
      </div>
    </div>
  );
}

export function syncDraftClassifierFromForm(
  draft: DocumentTypeDefinition,
  form: MatchRulesForm = emptyMatchRulesForm()
): DocumentTypeDefinition {
  return {
    ...draft,
    classifierCustomized: false,
    classifier: {
      ...draft.classifier,
      enabled: true,
      root: compileMatchRulesToClassifier(form),
    },
  };
}
