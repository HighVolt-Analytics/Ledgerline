import { describe, expect, it } from "vitest";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import {
  earlierRulesFromOtherMailboxes,
  globalPriorityContext,
} from "@/lib/emailIngestionRulesPriority";

function rule(id: string, mailbox: string, priority: number): EmailCaptureRule {
  return {
    id,
    name: id,
    enabled: true,
    priority,
    mailbox,
    root: { type: "group", operator: "AND", children: [] },
    action: { saveAttachment: true, routeTo: "Purchase Management", tags: [] },
    matchedCount: 0,
    lastMatched: "—",
  };
}

describe("emailIngestionRulesPriority", () => {
  it("ignores rules for disconnected mailboxes in earlier-external banner", () => {
    const all = [
      rule("stale", "vishnu@highvolt.tech", 1),
      rule("local", "mahendra@highvolt.tech", 2),
    ];
    const visible = [all[1]];
    const connected = ["mahendra@highvolt.tech"];
    expect(
      earlierRulesFromOtherMailboxes(all, "mahendra@highvolt.tech", visible, connected)
    ).toEqual([]);
  });

  it("counts priority only among rules effective for the mailbox", () => {
    const all = [
      rule("stale", "vishnu@highvolt.tech", 1),
      rule("local", "mahendra@highvolt.tech", 2),
      rule("org", "*", 100),
    ];
    const connected = ["mahendra@highvolt.tech"];
    expect(
      globalPriorityContext(all, all[1], "mahendra@highvolt.tech", connected)
    ).toEqual({ rank: 1, total: 2 });
  });
});
