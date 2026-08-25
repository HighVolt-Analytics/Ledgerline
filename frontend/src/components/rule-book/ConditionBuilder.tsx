import { Trash2 } from "lucide-react";
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
  { key: "equals", label: "is" },
  { key: "not_equals", label: "is not" },
  { key: "contains", label: "contains" },
  { key: "not_contains", label: "does not contain" },
  { key: "starts_with", label: "starts with" },
  { key: "ends_with", label: "ends with" },
  { key: "regex", label: "matches" },
];

const EMPTY_CONDITION = (): RuleCondition => ({
  type: "condition",
  field: "subject",
  operator: "contains",
  value: "",
});

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

function removeAndPrune(root: RuleConditionGroup, path: number[]): RuleConditionGroup {
  let next = removeAtPath(root, path);
  if (path.length <= 1) return next;
  const parentPath = path.slice(0, -1);
  const parent = groupAt(next, parentPath);
  if (parent && parent.children.length === 0) {
    next = removeAtPath(next, parentPath);
  }
  return next;
}

function groupAt(root: RuleConditionGroup, path: number[]): RuleConditionGroup | null {
  let node: RuleConditionGroup = root;
  for (const index of path) {
    const child = node.children[index];
    if (!child || child.type !== "group") return null;
    node = child;
  }
  return node;
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
    <div className="condition-builder__row" data-testid={`condition-${idx}`}>
      <Select
        value={cond.field}
        disabled={readOnly}
        onValueChange={(field) => onChange({ ...cond, field: field as EmailField })}
        options={FIELDS.map((f) => ({ value: f.key, label: f.label }))}
        className="condition-builder__select"
      />
      <Select
        value={cond.operator}
        disabled={readOnly}
        onValueChange={(operator) =>
          onChange({ ...cond, operator: operator as ConditionOperator })
        }
        options={OPERATORS.map((o) => ({ value: o.key, label: o.label }))}
        className="condition-builder__select"
      />
      <input
        type="text"
        value={cond.value}
        disabled={readOnly}
        onChange={(e) => onChange({ ...cond, value: e.target.value })}
        className="condition-builder__value"
        placeholder="value"
        data-testid={`condition-value-${idx}`}
      />
      {!readOnly ? (
        <button
          type="button"
          className="condition-builder__icon-btn"
          onClick={onRemove}
          aria-label="Remove condition"
          data-testid={`condition-delete-${idx}`}
        >
          <Trash2 />
        </button>
      ) : (
        <span />
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
  const pathKey = path.join("-") || "root";
  const nested = depth > 0;

  const toggleOp = () => {
    onChange(
      updateAtPath(root, path, (g) => ({
        ...g,
        operator: g.operator === "AND" ? "OR" : "AND",
      }))
    );
  };

  const addCondition = () => {
    onChange(
      updateAtPath(root, path, (g) => ({
        ...g,
        children: [...g.children, EMPTY_CONDITION()],
      }))
    );
  };

  const addGroup = () => {
    onChange(
      updateAtPath(root, path, (g) => ({
        ...g,
        children: [
          ...g.children,
          { type: "group", operator: "AND", children: [EMPTY_CONDITION()] },
        ],
      }))
    );
  };

  const opControl =
    group.children.length > 0 ? (
      <button
        type="button"
        disabled={readOnly}
        onClick={toggleOp}
        className="condition-builder__op"
        title={group.operator === "AND" ? "All must match — click for any" : "Any may match — click for all"}
        data-testid={`group-op-${pathKey}`}
      >
        {group.operator}
      </button>
    ) : (
      <span className="condition-builder__op-gap" />
    );

  return (
    <div className={cn("condition-builder", nested && "condition-builder--nested")}>
      {group.children.map((child, idx) => {
        const childPath = [...path, idx];
        const childKey = childPath.join("-");
        return (
          <div key={childKey} className="condition-builder__line">
            {idx === 0 ? opControl : <span className="condition-builder__op-gap" />}
            {child.type === "group" ? (
              <GroupEditor
                group={child}
                path={childPath}
                root={root}
                onChange={onChange}
                readOnly={readOnly}
                depth={depth + 1}
              />
            ) : (
              <ConditionRow
                cond={child}
                readOnly={readOnly}
                idx={childKey}
                onChange={(next) => {
                  onChange(
                    updateAtPath(root, path, (g) => ({
                      ...g,
                      children: g.children.map((c, i) => (i === idx ? next : c)),
                    }))
                  );
                }}
                onRemove={() => onChange(removeAndPrune(root, childPath))}
              />
            )}
          </div>
        );
      })}

      {!readOnly ? (
        <div className="condition-builder__line">
          <span className="condition-builder__op-gap" />
          <div className="condition-builder__add">
            <button
              type="button"
              className="condition-builder__add-btn"
              onClick={addCondition}
              data-testid={`add-condition-${pathKey}`}
            >
              + Condition
            </button>
            {depth < 1 ? (
              <button
                type="button"
                className="condition-builder__add-btn"
                onClick={addGroup}
                data-testid={`add-group-${pathKey}`}
              >
                + Group
              </button>
            ) : (
              <button
                type="button"
                className="condition-builder__add-btn condition-builder__add-btn--muted"
                onClick={() => onChange(removeAtPath(root, path))}
                data-testid={`group-delete-${pathKey}`}
              >
                Remove group
              </button>
            )}
          </div>
        </div>
      ) : null}
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
  compact?: boolean;
}) {
  return (
    <GroupEditor group={root} path={[]} root={root} onChange={onChange} readOnly={readOnly} />
  );
}
