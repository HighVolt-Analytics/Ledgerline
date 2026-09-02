import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import { withSerialPriorities } from "@/lib/rulePriority";

/** Wildcard — ingestion rules apply to every connected mailbox for the org. */
export const DEFAULT_INGESTION_MAILBOX = "*";

/** True when a rule applies to the given connected mailbox (mirrors backend mailbox scope). */
export function ruleAppliesToMailbox(
  rule: EmailCaptureRule,
  mailboxEmail: string
): boolean {
  const scope = rule.mailbox.trim().toLowerCase();
  if (!scope || scope === "*") return true;
  return scope === mailboxEmail.trim().toLowerCase();
}

function normalizeMailboxEmail(email: string): string {
  return email.trim().toLowerCase();
}

/** True when a rule's mailbox scope is org-wide (*) or a currently connected mailbox. */
export function ruleMailboxIsConnected(
  rule: EmailCaptureRule,
  connectedMailboxEmails: string[]
): boolean {
  const scope = rule.mailbox.trim().toLowerCase();
  if (!scope || scope === "*") return true;
  const connected = new Set(connectedMailboxEmails.map(normalizeMailboxEmail));
  return connected.has(scope);
}

/** Rules scoped to a mailbox that is not connected for this tenant (ignored at ingest). */
export function orphanedMailboxRules(
  rules: EmailCaptureRule[],
  connectedMailboxEmails: string[]
): EmailCaptureRule[] {
  return rules.filter((rule) => !ruleMailboxIsConnected(rule, connectedMailboxEmails));
}

/** Rules that participate in ingest evaluation for one connected mailbox. */
export function rulesEffectiveForMailbox(
  rules: EmailCaptureRule[],
  mailboxEmail: string,
  connectedMailboxEmails?: string[]
): EmailCaptureRule[] {
  return rules.filter(
    (rule) =>
      ruleAppliesToMailbox(rule, mailboxEmail) &&
      (connectedMailboxEmails == null || ruleMailboxIsConnected(rule, connectedMailboxEmails))
  );
}

/** Rules visible when editing ingestion for one connected mailbox. */
export function filterRulesForMailbox(
  rules: EmailCaptureRule[],
  mailboxEmail: string
): EmailCaptureRule[] {
  return rules.filter((rule) => ruleAppliesToMailbox(rule, mailboxEmail));
}

/** Merge edited mailbox-visible rules back into the tenant-wide rule list. */
export function mergeMailboxIngestionRules(
  allRules: EmailCaptureRule[],
  mailboxEmail: string,
  nextVisibleRules: EmailCaptureRule[]
): EmailCaptureRule[] {
  const visibleIds = new Set(
    filterRulesForMailbox(allRules, mailboxEmail).map((rule) => rule.id)
  );
  const kept = allRules.filter((rule) => !visibleIds.has(rule.id));
  return withSerialPriorities([...kept, ...nextVisibleRules]);
}
