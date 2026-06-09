import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import type {
  EmailField,
  ConditionOperator,
  RuleCondition,
  RuleConditionGroup,
} from "@/lib/v4RuleBookTypes";

const FIELDS: { key: EmailField; label: string }[] = [
  { key: "from", label: "From" },
  { key: "to", label: "To" },
  { key: "subject", label: "Subject" },
  { key: "body", label: "Body" },
  { key: "attachment_name", label: "Attachment name" },
  { key: "attachment_mime", label: "Attachment MIME" },
];

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
  root: RuleConditionGroup,
  path: number[],
  updater: (node: RuleConditionGroup) => RuleConditionGroup
): RuleConditionGroup {
  if (path.length === 0) return updater(root);
  const [head, ...rest] = path;
  const children = root.children.map((child, idx) => {
    if (idx !== head) return child;
    if (child.type !== "group") return child;
    return updateAtPath(child, rest, updater);
  });
  return { ...root, children };
}

function removeAtPath(root: RuleConditionGroup, path: number[]): RuleConditionGroup {
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
  cond: RuleCondition;
  onChange: (next: RuleCondition) => void;
  onRemove: () => void;
  readOnly?: boolean;
  idx: string;
}) {
  return (
    <div
      className="flex flex-nowrap items-center gap-2 min-w-max"
      data-testid={`condition-${idx}`}
    >
      <Select
        value={cond.field}
        disabled={readOnly}
        onValueChange={(field) => onChange({ ...cond, field: field as EmailField })}
        options={FIELDS.map((f) => ({ value: f.key, label: f.label }))}
        className="w-[150px] shrink-0"
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
        placeholder="value"
        data-testid={`condition-value-${idx}`}
      />
      {!readOnly && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 shrink-0 p-0 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
          data-testid={`condition-delete-${idx}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      )}
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
  group: RuleConditionGroup;
  path: number[];
  root: RuleConditionGroup;
  onChange: (next: RuleConditionGroup) => void;
  readOnly?: boolean;
  depth?: number;
}) {
  const setRoot = (next: RuleConditionGroup) => onChange(next);
  const pathKey = path.join("-") || "root";

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
          { type: "condition", field: "subject", operator: "contains", value: "" },
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
          data-testid={`group-op-${pathKey}`}
        >
          {group.operator}
        </button>
        <span className="text-xs text-muted-foreground">
          {group.operator === "AND" ? "all conditions must match" : "any condition matches"}
        </span>
      </div>

      <div className="space-y-2 pl-3 border-l-2 border-border/60 overflow-x-auto">
        {group.children.length === 0 && (
          <p className="text-xs text-muted-foreground italic py-1">
            No conditions yet — add one below.
          </p>
        )}
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

      {!readOnly && (
        <div className="flex flex-wrap gap-2 mt-2.5 pl-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={addCondition}
            data-testid={`add-condition-${pathKey}`}
          >
            <Plus className="h-3.5 w-3.5 mr-1" /> Condition
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={addGroup}
            data-testid={`add-group-${pathKey}`}
          >
            <Plus className="h-3.5 w-3.5 mr-1" /> Group
          </Button>
        </div>
      )}
    </div>
  );
}

export function ConditionBuilder({
  root,
  onChange,
  readOnly,
}: {
  root: RuleConditionGroup;
  onChange: (next: RuleConditionGroup) => void;
  readOnly?: boolean;
}) {
  return <GroupEditor group={root} path={[]} root={root} onChange={onChange} readOnly={readOnly} />;
}
