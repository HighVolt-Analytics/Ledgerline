import type { TeamExpenseKind } from "@/lib/v4RuleBookTypes";
import { TEAM_EXPENSE_KINDS } from "@/lib/v4RuleBookTypes";

export function inferTeamExpenseKindFromLabels(
  ...labels: Array<string | null | undefined>
): TeamExpenseKind | null {
  const blob = labels
    .map((label) => (label ?? "").trim().toLowerCase())
    .filter(Boolean)
    .join(" ")
    .trim();
  if (!blob) return null;
  if (blob.includes("expense against advance")) return "expense_claim";
  if (blob.includes("expense claim") || blob.includes("reimbursement")) return "expense_claim";
  if (blob.includes("advance requisition") || blob.includes("advance request")) {
    return "advance_requisition";
  }
  if (blob.includes("employee advance") && !blob.includes("expense")) {
    return "advance_requisition";
  }
  return null;
}

export function reconcileTeamExpenseKindForDocumentType(input: {
  title?: string | null;
  shortTitle?: string | null;
  configured?: string | null;
}): string {
  const inferred = inferTeamExpenseKindFromLabels(input.title, input.shortTitle);
  const raw = (input.configured ?? "").trim().toLowerCase();
  const pinned = (TEAM_EXPENSE_KINDS as readonly string[]).includes(raw)
    ? (raw as TeamExpenseKind)
    : null;
  if (inferred) {
    if (pinned && pinned !== inferred) return inferred;
    return pinned ?? inferred;
  }
  return pinned ?? "";
}
