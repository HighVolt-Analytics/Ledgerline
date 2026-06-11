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
