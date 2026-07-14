/** Architecture §2.2 — default priority 100 with 10-step gap between rules. */

export const RULE_PRIORITY_BASE = 100;
export const RULE_PRIORITY_STEP = 10;

export function nextRulePriority(rules: Array<{ priority?: number }>): number {
  if (rules.length === 0) {
    return RULE_PRIORITY_BASE;
  }
  const max = Math.max(...rules.map((rule) => rule.priority ?? RULE_PRIORITY_BASE));
  return max + RULE_PRIORITY_STEP;
}

export function sortByPriority<T extends { priority?: number }>(rules: T[]): T[] {
  return [...rules].sort(
    (a, b) => (a.priority ?? RULE_PRIORITY_BASE) - (b.priority ?? RULE_PRIORITY_BASE)
  );
}

/** Ingestion rules: evaluation order is 1..n (first match wins). */
export function nextSerialPriority(rules: Array<{ priority?: number }>): number {
  if (rules.length === 0) {
    return 1;
  }
  const max = Math.max(...rules.map((rule) => rule.priority ?? 0));
  return Math.max(max, rules.length) + 1;
}

/** Assign priority 1..n from current array order (does not re-sort). */
export function assignSerialPriorities<T extends { priority?: number }>(rules: T[]): T[] {
  return rules.map((rule, index) => ({
    ...rule,
    priority: index + 1,
  }));
}

/** Sort by priority, then renumber to 1..n. */
export function withSerialPriorities<T extends { priority?: number }>(rules: T[]): T[] {
  return assignSerialPriorities(sortByPriority(rules));
}

export function moveRuleInPriorityOrder<T extends { id: string; priority?: number }>(
  rules: T[],
  id: string,
  direction: -1 | 1
): T[] {
  const sorted = sortByPriority(rules);
  const index = sorted.findIndex((rule) => rule.id === id);
  const swap = index + direction;
  if (index < 0 || swap < 0 || swap >= sorted.length) {
    return rules;
  }
  const next = [...sorted];
  const a = next[index];
  const b = next[swap];
  if (!a || !b) {
    return rules;
  }
  next[index] = b;
  next[swap] = a;
  return assignSerialPriorities(next);
}
