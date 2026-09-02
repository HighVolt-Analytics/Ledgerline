import type { RuleBookConfig } from "@/api/types";

import type { EmailCaptureRule, RuleConditionGroup } from "@/lib/v4RuleBookTypes";

import { INGEST_ACTION_ROUTE_PLACEHOLDER } from "@/lib/v4RuleBookTypes";

import { deriveRequiresEmployeeSenderForSave } from "@/lib/emailIngestionRuleValidation";

import { withSerialPriorities } from "@/lib/rulePriority";



function mapConditionGroup(root: Record<string, unknown>): RuleConditionGroup {

  return root as unknown as RuleConditionGroup;

}



function conditionGroupToApi(root: RuleConditionGroup): Record<string, unknown> {

  return root as unknown as Record<string, unknown>;

}



export function emailCaptureRulesFromApi(

  api: Pick<RuleBookConfig, "email_capture_rules">

): EmailCaptureRule[] {

  return (api.email_capture_rules ?? []).map((rule) => ({

    id: rule.id,

    name: rule.name,

    enabled: rule.enabled,

    priority: rule.priority,

    mailbox: rule.mailbox,

    root: mapConditionGroup(rule.root),

    action: {

      saveAttachment: rule.action.save_attachment,

      routeTo: rule.action.route_to,

      tags: rule.action.tags,

    },

    requiresEmployeeSender: rule.requires_employee_sender ?? null,

    matchedCount: rule.matched_count ?? 0,

    lastMatched: rule.last_matched ?? "—",

  }));

}



export function emailIngestionRulesLoadFromApi(api: {

  email_capture_rules: RuleBookConfig["email_capture_rules"];

  rule_warnings?: Record<string, string[]>;
  warnings?: string[];
}) {
  return {
    rules: emailCaptureRulesFromApi(api),
    ruleWarnings: api.rule_warnings ?? {},
    warnings: api.warnings ?? [],
  };
}



export function emailCaptureRulesToApi(rules: EmailCaptureRule[]) {

  return withSerialPriorities(rules).map((rule) => ({

    id: rule.id,

    name: rule.name,

    enabled: rule.enabled,

    priority: rule.priority,

    mailbox: rule.mailbox,

    root: conditionGroupToApi(rule.root),

    action: {

      save_attachment: rule.action.saveAttachment,

      route_to: rule.action.routeTo || INGEST_ACTION_ROUTE_PLACEHOLDER,

      tags: rule.action.tags,

    },

    requires_employee_sender: deriveRequiresEmployeeSenderForSave(rule),

  }));

}

