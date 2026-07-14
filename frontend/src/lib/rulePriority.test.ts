import { describe, expect, it } from "vitest";
import {
  moveRuleInPriorityOrder,
  nextSerialPriority,
  withSerialPriorities,
} from "./rulePriority";

describe("serial priorities (ingestion)", () => {
  it("nextSerialPriority starts at 1 and increments from max", () => {
    expect(nextSerialPriority([])).toBe(1);
    expect(nextSerialPriority([{ priority: 1 }, { priority: 2 }])).toBe(3);
    expect(nextSerialPriority([{ priority: 10 }])).toBe(11);
  });

  it("withSerialPriorities renumbers to 1..n in priority order", () => {
    const rules = [
      { id: "b", priority: 50 },
      { id: "a", priority: 10 },
      { id: "c", priority: 100 },
    ];
    expect(withSerialPriorities(rules)).toEqual([
      { id: "a", priority: 1 },
      { id: "b", priority: 2 },
      { id: "c", priority: 3 },
    ]);
  });

  it("moveRuleInPriorityOrder swaps and renumbers", () => {
    const rules = [
      { id: "a", priority: 1 },
      { id: "b", priority: 2 },
      { id: "c", priority: 3 },
    ];
    expect(moveRuleInPriorityOrder(rules, "b", -1).map((r) => r.id)).toEqual(["b", "a", "c"]);
    expect(moveRuleInPriorityOrder(rules, "a", -1)).toEqual(rules);
    expect(moveRuleInPriorityOrder(rules, "c", 1)).toEqual(rules);
  });
});
