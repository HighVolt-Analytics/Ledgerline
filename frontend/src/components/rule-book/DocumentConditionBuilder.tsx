import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import type { ConditionOperator } from "@/lib/v4RuleBookTypes";
import type { DocumentRuleCondition, DocumentRuleConditionGroup } from "@/lib/v5DocumentTypes";

const FIELDS = [
  { key: "attachment_name", label: "Attachment name" },
  { key: "email_sender", label: "Email sender" },
  { key: "email_subject", label: "Email subject" },
  { key: "vendor", label: "Vendor" },
  { key: "invoice_no", label: "Invoice number" },
  { key: "po_reference", label: "PO reference" },
  { key: "line_text", label: "Line descriptions" },
  { key: "document_text", label: "Document text (OCR body)" },
  { key: "document_heading", label: "Document heading (OCR title)" },
  { key: "abn", label: "ABN" },
  { key: "capture_channel", label: "Capture channel" },
  { key: "has_po_reference", label: "Has PO reference" },
  { key: "has_invoice_no", label: "Has invoice number" },
  { key: "has_total", label: "Has total amount" },
  { key: "is_commercial_invoice", label: "Is commercial invoice" },
  { key: "has_heading_invoice", label: "Heading is invoice / tax invoice" },
  { key: "has_heading_po", label: "Heading is purchase order" },
  { key: "has_heading_grn", label: "Heading is GRN / delivery note" },
  { key: "has_heading_credit_note", label: "Heading is credit note" },
  { key: "has_heading_quote", label: "Heading is quote / quotation" },
  { key: "has_heading_contract", label: "Heading is contract / agreement" },
] as const;

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
  "h-8 w-[180px] shrink-0 rounded-md border border-input bg-background px-2 text-xs font-mono shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

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
}: {
  cond: DocumentRuleCondition;
  onChange: (next: DocumentRuleCondition) => void;
  onRemove: () => void;
  readOnly?: boolean;
  idx: string;
}) {
  return (
    <div className="flex flex-nowrap items-center gap-2 min-w-max" data-testid={`dt-condition-${idx}`}>
      <Select
        value={cond.field}
        disabled={readOnly}
        onValueChange={(field) => onChange({ ...cond, field })}
        options={FIELDS.map((f) => ({ value: f.key, label: f.label }))}
        className="w-[170px] shrink-0"
      />
      <Select
        value={cond.operator}
        disabled={readOnly}
        onValueChange={(operator) =>
          onChange({ ...cond, operator: operator as ConditionOperator })
        }
        options={OPERATORS.map((o) => ({ value: o.key, label: o.label }))}
        className="w-[130px] shrink-0"
      />
      <input
        type="text"
        value={cond.value}
        disabled={readOnly}
        onChange={(e) => onChange({ ...cond, value: e.target.value })}
        className={valueInputCls}
        placeholder={cond.field.startsWith("has_") || cond.field.startsWith("is_") ? "true / false" : "value"}
        data-testid={`dt-condition-value-${idx}`}
      />
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
}: {
  group: DocumentRuleConditionGroup;
  path: number[];
  root: DocumentRuleConditionGroup;
  onChange: (next: DocumentRuleConditionGroup) => void;
  readOnly?: boolean;
  depth?: number;
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
            field: "vendor",
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
              />
            );
          }
          return (
            <ConditionRow
              key={childKey}
              cond={child}
              readOnly={readOnly}
              idx={childKey}
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
}: {
  root: DocumentRuleConditionGroup;
  onChange: (next: DocumentRuleConditionGroup) => void;
  readOnly?: boolean;
}) {
  return <GroupEditor group={root} path={[]} root={root} onChange={onChange} readOnly={readOnly} />;
}
