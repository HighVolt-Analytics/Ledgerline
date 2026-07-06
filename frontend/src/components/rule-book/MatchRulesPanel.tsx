import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { MatchRuleFieldSelect } from "@/components/rule-book/MatchRuleFieldSelect";
import { cn } from "@/lib/cn";
import type { ConditionOperator } from "@/lib/v4RuleBookTypes";
import {
  BOOLEAN_OPERATORS,
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
  withRowKey,
} from "@/lib/documentMatchRules";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { formatExtractionFieldKeyInput } from "@/lib/documentExtractionFields";

function defaultTextRule(): MatchRuleRow {
  return withRowKey({ field: "document_heading", operator: "contains", value: "" });
}

function defaultExcludeRule(): MatchRuleRow {
  return withRowKey({ field: "document_heading", operator: "contains", value: "" });
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
                field: formatExtractionFieldKeyInput(e.target.value),
                operator: isMatchRuleBooleanField(e.target.value) ? "equals" : row.operator,
              })
            }
            placeholder="custom_field_name"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
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
            key={row.rowKey ?? index}
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

export function MatchRulesPanel({
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
        extraction fields under Processing, Fields to use them here as match rules.
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
        title="Do not match if"
        hint={
          form.excludeMode === "any"
            ? 'Exclude when any rule matches. "Has ..." field checks also suppress those fields after OCR.'
            : 'Exclude only when all rules match. "Has ..." field checks also suppress those fields after OCR.'
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

export function syncDraftClassifierFromForm(
  draft: DocumentTypeDefinition,
  form: MatchRulesForm = emptyMatchRulesForm()
): DocumentTypeDefinition {
  return documentTypeWithMatchRulesForm(draft, form);
}
