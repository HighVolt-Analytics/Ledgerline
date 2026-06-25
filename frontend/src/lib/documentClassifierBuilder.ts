/**
 * Build document-type classifier trees from user-friendly recognition signals.
 * Signal definitions are loaded from GET /api/rule-book/recognition-signals.
 */

import type {
  DocumentRuleCondition,
  DocumentRuleConditionGroup,
  DocumentTypeClassifier,
} from "@/lib/v5DocumentTypes";
import {
  pickGroups,
  signalConditionFromCatalog,
  supportingGuardConditions,
  weakSignalSet,
  type RecognitionSignalId,
} from "@/lib/recognitionSignalCatalog";

export type { RecognitionSignalId } from "@/lib/recognitionSignalCatalog";

export type ClassifierLayout = "any_signal" | "all_signals" | "supporting_doc" | "grouped";

const cond = (
  field: string,
  operator: DocumentRuleCondition["operator"],
  value: string
): DocumentRuleCondition => ({
  type: "condition",
  field,
  operator,
  value,
});

const orGroup = (children: DocumentRuleCondition[]): DocumentRuleConditionGroup => ({
  type: "group",
  operator: "OR",
  children,
});

const andGroup = (
  children: Array<DocumentRuleCondition | DocumentRuleConditionGroup>
): DocumentRuleConditionGroup => ({
  type: "group",
  operator: "AND",
  children,
});

/** Map each checkbox id to one classifier leaf condition. */
export function signalToCondition(signalId: RecognitionSignalId): DocumentRuleCondition {
  return (
    signalConditionFromCatalog(signalId) ?? cond("document_text", "contains", "")
  );
}

function buildGroupedIdentityTree(
  signalIds: RecognitionSignalId[]
): DocumentRuleConditionGroup | DocumentRuleCondition | null {
  const available = new Set(signalIds);
  const andChildren: Array<DocumentRuleCondition | DocumentRuleConditionGroup> = [];
  const used = new Set<RecognitionSignalId>();
  const weakSignals = weakSignalSet();
  const groups = pickGroups();

  for (const group of groups) {
    const matched = group.filter((id) => available.has(id));
    if (matched.length === 0) continue;
    matched.forEach((id) => used.add(id));
    if (matched.length === 1) {
      andChildren.push(signalToCondition(matched[0]));
    } else {
      andChildren.push(orGroup(matched.map(signalToCondition)));
    }
  }

  const ungrouped = signalIds.filter((id) => !used.has(id) && !weakSignals.has(id));
  if (ungrouped.length === 1) {
    andChildren.push(signalToCondition(ungrouped[0]));
  } else if (ungrouped.length > 1) {
    andChildren.push(orGroup(ungrouped.map(signalToCondition)));
  }

  for (const id of signalIds) {
    if (weakSignals.has(id)) {
      andChildren.push(signalToCondition(id));
    }
  }

  if (andChildren.length === 0) return null;
  if (andChildren.length === 1) return andChildren[0];
  return andGroup(andChildren);
}

export function buildClassifierRootGrouped(
  signalIds: RecognitionSignalId[]
): DocumentRuleConditionGroup {
  const tree = buildGroupedIdentityTree(signalIds);
  return tree?.type === "group"
    ? tree
    : tree
      ? andGroup([tree])
      : { type: "group", operator: "AND", children: [] };
}

export function buildClassifierRoot(
  signalIds: RecognitionSignalId[],
  layout: ClassifierLayout
): DocumentRuleConditionGroup {
  const leaves = signalIds.map(signalToCondition);
  if (leaves.length === 0) {
    return { type: "group", operator: "AND", children: [] };
  }

  if (layout === "grouped") {
    return buildClassifierRootGrouped(signalIds);
  }

  if (layout === "all_signals") {
    return andGroup(leaves);
  }

  if (layout === "supporting_doc") {
    const grouped = buildGroupedIdentityTree(signalIds);
    const identity =
      grouped?.type === "group"
        ? grouped
        : grouped
          ? orGroup([grouped])
          : orGroup(leaves);
    return andGroup([identity, ...supportingGuardConditions()]);
  }

  return orGroup(leaves);
}

export function buildClassifierFromSignals(
  signalIds: RecognitionSignalId[],
  layout: ClassifierLayout,
  options: { priority: number; confidence?: number; enabled?: boolean }
): DocumentTypeClassifier {
  return {
    enabled: options.enabled ?? true,
    priority: options.priority,
    confidence: options.confidence ?? 0.85,
    root: buildClassifierRoot(signalIds, layout),
  };
}

function conditionMatchesSignal(
  condition: DocumentRuleCondition,
  signalId: RecognitionSignalId
): boolean {
  const expected = signalToCondition(signalId);
  return (
    condition.field === expected.field &&
    condition.operator === expected.operator &&
    String(condition.value ?? "") === String(expected.value ?? "")
  );
}

function collectConditions(
  node: DocumentRuleCondition | DocumentRuleConditionGroup
): DocumentRuleCondition[] {
  if (node.type === "condition") return [node];
  return node.children.flatMap((child) => collectConditions(child));
}

/** Best-effort: recover simple-mode checkboxes from a stored classifier tree. */
export function parseSignalsFromClassifier(
  root: DocumentRuleConditionGroup,
  allowed: RecognitionSignalId[]
): RecognitionSignalId[] {
  const leaves = collectConditions(root);
  const found: RecognitionSignalId[] = [];
  for (const signalId of allowed) {
    if (leaves.some((leaf) => conditionMatchesSignal(leaf, signalId))) {
      found.push(signalId);
    }
  }
  return found;
}

export function isSupportingDocClassifier(root: DocumentRuleConditionGroup): boolean {
  const leaves = collectConditions(root);
  return (
    leaves.some((l) => l.field === "has_invoice_no" && l.value === "false") &&
    leaves.some((l) => l.field === "is_commercial_invoice" && l.value === "false")
  );
}

export function inferClassifierLayout(root: DocumentRuleConditionGroup): ClassifierLayout {
  if (root.operator === "AND" && isSupportingDocClassifier(root)) {
    return "supporting_doc";
  }
  if (root.operator === "AND" && root.children.every((c) => c.type === "condition")) {
    return "all_signals";
  }
  return "any_signal";
}
