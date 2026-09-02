import { sortByPriority } from "@/lib/rulePriority";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import {
  ruleAppliesToMailbox,
  ruleMailboxIsConnected,
  rulesEffectiveForMailbox,
} from "@/lib/emailIngestionRules";

export type EarlierExternalRule = {
  id: string;
  name: string;
  mailbox: string;
  priority: number;
};

/** Enabled rules from other connected mailboxes with lower stored priority (informational only). */
export function earlierRulesFromOtherMailboxes(
  allRules: EmailCaptureRule[],
  mailboxEmail: string,
  visibleRules: EmailCaptureRule[],
  connectedMailboxEmails: string[]
): EarlierExternalRule[] {
  const enabled = allRules.filter(
    (rule) => rule.enabled && ruleMailboxIsConnected(rule, connectedMailboxEmails)
  );
  if (visibleRules.length === 0) return [];
  const minVisiblePriority = Math.min(...visibleRules.map((rule) => rule.priority));
  return sortByPriority(enabled)
    .filter(
      (rule) =>
        !ruleAppliesToMailbox(rule, mailboxEmail) && rule.priority < minVisiblePriority
    )
    .map((rule) => ({
      id: rule.id,
      name: rule.name,
      mailbox: rule.mailbox,
      priority: rule.priority,
    }));
}

export function globalPriorityContext(
  allRules: EmailCaptureRule[],
  rule: EmailCaptureRule,
  mailboxEmail: string,
  connectedMailboxEmails?: string[]
): { rank: number; total: number } {
  const enabled = sortByPriority(
    rulesEffectiveForMailbox(
      allRules.filter((row) => row.enabled),
      mailboxEmail,
      connectedMailboxEmails
    )
  );
  const rank = enabled.findIndex((row) => row.id === rule.id) + 1;
  return { rank: rank > 0 ? rank : rule.priority, total: enabled.length || 1 };
}
