import type { EmailCaptureRule, RuleConditionGroup } from "@/lib/v4RuleBookTypes";

export const EMPLOYEE_BYPASS_RULE_ID = "ec-employee-bypass";

const EMPTY_VALUE_OPERATORS = new Set(["contains", "not_contains", "starts_with", "ends_with"]);

function walkConditions(root: RuleConditionGroup): Array<{ field: string; operator: string; value: string }> {
  const leaves: Array<{ field: string; operator: string; value: string }> = [];
  for (const child of root.children) {
    if (child.type === "group") {
      leaves.push(...walkConditions(child));
    } else {
      leaves.push({
        field: child.field,
        operator: child.operator,
        value: child.value,
      });
    }
  }
  return leaves;
}

function conditionIsTriviallyTrue(condition: { operator: string; value: string }): boolean {
  const op = condition.operator;
  const value = condition.value.trim();
  if (EMPTY_VALUE_OPERATORS.has(op) && !value) return false;
  if (op === "regex" && !value) return true;
  return false;
}

function isTriviallyTrueTree(root: RuleConditionGroup): boolean {
  const leaves = walkConditions(root);
  if (leaves.length === 0) return true;
  if (root.operator === "AND") {
    return leaves.every(conditionIsTriviallyTrue);
  }
  return leaves.some(conditionIsTriviallyTrue);
}

/** Mirror backend validate_rule_specificity for load-time and live inline warnings. */
export function validateEmailCaptureRuleSpecificity(rule: EmailCaptureRule): string[] {
  const warnings: string[] = [];
  const mailbox = rule.mailbox.trim();
  if (!mailbox || mailbox === "*") {
    if (isTriviallyTrueTree(rule.root)) {
      warnings.push(
        `Rule "${rule.name}" applies to all mailboxes (*) with empty or trivially-true conditions — it would match every attachment.`
      );
    }
  }
  for (const leaf of walkConditions(rule.root)) {
    if (EMPTY_VALUE_OPERATORS.has(leaf.operator) && !leaf.value.trim()) {
      warnings.push(
        `Rule "${rule.name}" has an empty value for ${leaf.field} / ${leaf.operator} — this condition will never match.`
      );
    }
  }
  return warnings;
}

export function validateEmailCaptureRulesWarningsById(
  rules: EmailCaptureRule[]
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const rule of rules) {
    const warnings = validateEmailCaptureRuleSpecificity(rule);
    if (warnings.length > 0) out[rule.id] = warnings;
  }
  return out;
}

export function inferRequiresEmployeeSender(rule: EmailCaptureRule): boolean {
  if (rule.requiresEmployeeSender != null) return rule.requiresEmployeeSender;
  if (rule.action.routeTo === "Team Expenses") return true;
  if (rule.id === EMPLOYEE_BYPASS_RULE_ID) return true;
  return false;
}

export function ruleShowsEmployeeSenderGate(rule: EmailCaptureRule): boolean {
  return inferRequiresEmployeeSender(rule);
}

export function employeeSenderGateTooltip(rule: EmailCaptureRule): string {
  if (rule.id === EMPLOYEE_BYPASS_RULE_ID) {
    return "Built-in employee attachment rule — only registered employees can ingest through this rule.";
  }
  if (rule.requiresEmployeeSender) {
    return "When enabled, the sender email must match a registered employee or the attachment is skipped.";
  }
  return "Requires sender to be a registered employee.";
}

export function deriveRequiresEmployeeSenderForSave(rule: EmailCaptureRule): boolean {
  if (rule.id === EMPLOYEE_BYPASS_RULE_ID) return true;
  return Boolean(rule.requiresEmployeeSender);
}
