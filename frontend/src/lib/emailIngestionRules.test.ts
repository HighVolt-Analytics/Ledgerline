import { describe, expect, it } from "vitest";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import {
  filterRulesForMailbox,
  mergeMailboxIngestionRules,
  ruleAppliesToMailbox,
} from "@/lib/emailIngestionRules";

function rule(id: string, mailbox: string): EmailCaptureRule {
  return {
    id,
    name: id,
    enabled: true,
    priority: 1,
    mailbox,
    root: { type: "group", operator: "AND", children: [] },
    action: { saveAttachment: true, routeTo: "Purchase Management", tags: [] },
    matchedCount: 0,
    lastMatched: "",
  };
}

describe("emailIngestionRules", () => {
  it("matches org-wide and mailbox-specific rules", () => {
    expect(ruleAppliesToMailbox(rule("a", "*"), "finance@co.com")).toBe(true);
    expect(ruleAppliesToMailbox(rule("b", "finance@co.com"), "finance@co.com")).toBe(true);
    expect(ruleAppliesToMailbox(rule("b", "finance@co.com"), "ap@co.com")).toBe(false);
  });

  it("filters and merges mailbox edits without dropping other mailboxes", () => {
    const all = [
      rule("org", "*"),
      rule("finance", "finance@co.com"),
      rule("ap", "ap@co.com"),
    ];
    const visible = filterRulesForMailbox(all, "finance@co.com");
    expect(visible.map((item) => item.id)).toEqual(["org", "finance"]);

    const nextVisible = [
      { ...visible[0], name: "Updated org rule" },
      { ...visible[1], name: "Updated finance rule" },
      rule("finance-new", "finance@co.com"),
    ];
    const merged = mergeMailboxIngestionRules(all, "finance@co.com", nextVisible);
    expect(merged.map((item) => item.id)).toEqual(["ap", "org", "finance", "finance-new"]);
    expect(merged.find((item) => item.id === "org")?.name).toBe("Updated org rule");
    expect(merged.find((item) => item.id === "ap")?.name).toBe("ap");
  });
});
