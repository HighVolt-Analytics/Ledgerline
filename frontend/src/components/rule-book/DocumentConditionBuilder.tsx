import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { MatchRuleFieldSelect } from "@/components/rule-book/MatchRuleFieldSelect";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import {
  BOOLEAN_OPERATORS,
  CUSTOM_MATCH_RULE_FIELD,
  isMatchRuleBooleanField,
  matchRuleFieldGroupsForDocumentType,
} from "@/lib/documentMatchRules";
import type { ConditionOperator } from "@/lib/v4RuleBookTypes";
import type { DocumentRuleCondition, DocumentRuleConditionGroup } from "@/lib/v5DocumentTypes";
import { formatExtractionFieldKeyInput } from "@/lib/documentExtractionFields";

const OPERATORS: { key: ConditionOperator; label: string }[] = [
  { key: "equals", label: "equals" },
  { key: "not_equals", label: "not equals" },
  { key: "contains", label: "contains" },
  { key: "not_contains", label: "not contains" },
  { key: "starts_with", label: "starts with" },
  { key: "ends_with", label: "ends with" },
  { key: "regex", label: "matches regex" },
];

const valueInputCls =
  "h-8 w-[180px] shrink-0 rounded-md border border-border bg-field px-2 text-xs font-mono shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

function updateAtPath(
  root: DocumentRuleConditionGroup,
  path: number[],
  updater: (node: DocumentRuleConditionGroup) => DocumentRuleConditionGroup
): DocumentRuleConditionGroup {
  if (path.length === 0) return updater(root);
  const [head, ...rest] = path;
  const children = root.children.map((child, idx) => {
    if (idx !== head) return child;
    if (child.type !== "group") return child;
    return updateAtPath(child, rest, updater);
  });
  return { ...root, children };
}

function removeAtPath(root: DocumentRuleConditionGroup, path: number[]): DocumentRuleConditionGroup {
  if (path.length === 1) {
    return { ...root, children: root.children.filter((_, i) => i !== path[0]) };
  }
  const [head, ...rest] = path;
  const children = root.children.map((child, idx) => {
    if (idx !== head || child.type !== "group") return child;
    return removeAtPath(child, rest);
  });
  return { ...root, children };
}

function ConditionRow({
  cond,
  onChange,
  onRemove,
  readOnly,
  idx,
  fieldGroups,
}: {
  cond: DocumentRuleCondition;
  onChange: (next: DocumentRuleCondition) => void;
  onRemove: () => void;
  readOnly?: boolean;
  idx: string;
  fieldGroups: ReturnType<typeof matchRuleFieldGroupsForDocumentType>;
}) {
  const catalogKeys = useMemo(
    () => new Set(fieldGroups.flatMap((group) => group.fields.map((field) => field.key))),
    [fieldGroups]
  );
  const [customKeyMode, setCustomKeyMode] = useState(
    () => cond.field !== "" && !catalogKeys.has(cond.field)
  );
  const useCustomInput = customKeyMode || (cond.field !== "" && !catalogKeys.has(cond.field));
  const isBoolean = isMatchRuleBooleanField(cond.field);
  const operators = isBoolean ? BOOLEAN_OPERATORS : OPERATORS;

  return (
    <div className="flex flex-nowrap items-center gap-2 min-w-max" data-testid={`dt-condition-${idx}`}>
      {useCustomInput ? (
        <>
          <input
            type="text"
            value={cond.field}
            disabled={readOnly}
            onChange={(e) =>
              onChange({
                ...cond,
                field: formatExtractionFieldKeyInput(e.target.value),
                operator: isMatchRuleBooleanField(e.target.value) ? "equals" : cond.operator,
              })
            }
            placeholder="custom_field_name"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            className="h-8 w-[170px] shrink-0 rounded-md border border-input bg-background px-2 text-xs font-mono"
          />
          {!readOnly ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 px-2 text-[11px]"
              onClick={() => {
                setCustomKeyMode(false);
                onChange({
                  ...cond,
                  field: "document_heading",
                  operator: "contains",
                  value: "",
                });
              }}
            >
              Presets
            </Button>
          ) : null}
        </>
      ) : (
        <MatchRuleFieldSelect
          value={cond.field}
          groups={fieldGroups}
          disabled={readOnly}
          onValueChange={(field) => {
            if (field === CUSTOM_MATCH_RULE_FIELD) {
              setCustomKeyMode(true);
              onChange({ ...cond, field: "", operator: "contains", value: "" });
              return;
            }
            onChange(
              isMatchRuleBooleanField(field)
                ? { ...cond, field, operator: "equals", value: "true" }
                : { ...cond, field, operator: "contains" }
            );
          }}
          className="h-8 w-[170px] shrink-0"
        />
      )}
      <Select
        value={cond.operator}
        disabled={readOnly}
        onValueChange={(operator) =>
          onChange({ ...cond, operator: operator as ConditionOperator })
        }
        options={operators.map((o) => ({ value: o.key, label: o.label }))}
        className="w-[130px] shrink-0"
      />
      {isBoolean ? (
        <Select
          value={cond.value === "false" ? "false" : "true"}
          disabled={readOnly}
          onValueChange={(value) => onChange({ ...cond, value })}
          options={[
            { value: "true", label: "Yes / true" },
            { value: "false", label: "No / false" },
          ]}
          className="h-8 w-[120px] shrink-0 text-xs"
        />
      ) : (
        <input
          type="text"
          value={cond.value}
          disabled={readOnly}
          onChange={(e) => onChange({ ...cond, value: e.target.value })}
          className={valueInputCls}
          placeholder="value"
          data-testid={`dt-condition-value-${idx}`}
        />
      )}
      {!readOnly ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 shrink-0 p-0 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
          aria-label="Remove condition"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      ) : null}
    </div>
  );
}

function GroupEditor({
  group,
  path,
  root,
  onChange,
  readOnly,
  depth = 0,
  fieldGroups,
}: {
  group: DocumentRuleConditionGroup;
  path: number[];
  root: DocumentRuleConditionGroup;
  onChange: (next: DocumentRuleConditionGroup) => void;
  readOnly?: boolean;
  depth?: number;
  fieldGroups: ReturnType<typeof matchRuleFieldGroupsForDocumentType>;
}) {
  const setRoot = (next: DocumentRuleConditionGroup) => onChange(next);

  const toggleOp = () => {
    setRoot(
      updateAtPath(root, path, (g) => ({
        ...g,
        operator: g.operator === "AND" ? "OR" : "AND",
      }))
    );
  };

  const addCondition = () => {
    setRoot(
      updateAtPath(root, path, (g) => ({
        ...g,
        children: [
          ...g.children,
          {
            type: "condition",
            field: "document_heading",
            operator: "contains",
            value: "",
          },
        ],
      }))
    );
  };

  const addGroup = () => {
    setRoot(
      updateAtPath(root, path, (g) => ({
        ...g,
        children: [...g.children, { type: "group", operator: "AND", children: [] }],
      }))
    );
  };

  const opBtnCls =
    group.operator === "AND"
      ? "bg-primary/15 text-primary border-primary/30"
      : "bg-accent text-accent-foreground border-border";

  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        depth === 0 ? "border-border bg-muted/30" : "border-border/70 bg-background"
      )}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <button
          type="button"
          disabled={readOnly}
          onClick={toggleOp}
          className={cn(
            "inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-semibold tracking-wide transition-colors",
            opBtnCls,
            !readOnly && "hover:opacity-80 cursor-pointer"
          )}
        >
          {group.operator}
        </button>
        <span className="text-xs text-muted-foreground">
          {group.operator === "AND" ? "all conditions must match" : "any condition matches"}
        </span>
        {!readOnly && path.length > 0 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto h-8 w-8 shrink-0 p-0 text-muted-foreground hover:text-destructive"
            onClick={() => setRoot(removeAtPath(root, path))}
            aria-label="Remove group"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        ) : null}
      </div>

      <div className="space-y-2 pl-3 border-l-2 border-border/60 overflow-x-auto">
        {group.children.length === 0 ? (
          <p className="text-xs text-muted-foreground italic py-1">No conditions yet.</p>
        ) : null}
        {group.children.map((child, idx) => {
          const childPath = [...path, idx];
          const childKey = childPath.join("-");
          if (child.type === "group") {
            return (
              <GroupEditor
                key={childKey}
                group={child}
                path={childPath}
                root={root}
                onChange={onChange}
                readOnly={readOnly}
                depth={depth + 1}
                fieldGroups={fieldGroups}
              />
            );
          }
          return (
            <ConditionRow
              key={childKey}
              cond={child}
              readOnly={readOnly}
              idx={childKey}
              fieldGroups={fieldGroups}
              onChange={(next) => {
                setRoot(
                  updateAtPath(root, path, (g) => ({
                    ...g,
                    children: g.children.map((c, i) => (i === idx ? next : c)),
                  }))
                );
              }}
              onRemove={() => setRoot(removeAtPath(root, childPath))}
            />
          );
        })}
      </div>

      {!readOnly ? (
        <div className="flex flex-wrap gap-2 mt-2.5 pl-3">
          <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={addCondition}>
            <Plus className="h-3.5 w-3.5 mr-1" /> Condition
          </Button>
          <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={addGroup}>
            <Plus className="h-3.5 w-3.5 mr-1" /> Group
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function DocumentConditionBuilder({
  root,
  onChange,
  readOnly,
  extractionFields,
}: {
  root: DocumentRuleConditionGroup;
  onChange: (next: DocumentRuleConditionGroup) => void;
  readOnly?: boolean;
  extractionFields?: string[];
}) {
  const fieldGroups = useMemo(
    () => matchRuleFieldGroupsForDocumentType(extractionFields),
    [extractionFields]
  );

  return (
    <GroupEditor
      group={root}
      path={[]}
      root={root}
      onChange={onChange}
      readOnly={readOnly}
      fieldGroups={fieldGroups}
    />
  );
}
