import type {
  ApprovalChain,
  ApprovalChainEntry,
  ApprovalChainStep,
  Invoice,
} from "@/api/types";
import type { ApproverStep } from "@/lib/v4MockData";
import { APPROVAL_ROLES } from "@/lib/approvalPolicy";
import { formatTenantRole } from "@/lib/tenantRoles";

function documentSteps(chain: ApprovalChain | null | undefined): ApprovalChainStep[] {
  const steps = chain?.steps;
  if (!Array.isArray(steps) || steps.length === 0) return [];
  return steps.filter((s) => s && s.kind === "document");
}

/** Prefer matrix display labels; fall back to tenant-role formatting for slugs. */
function approvalRoleLabel(raw: string | null | undefined): string {
  const text = String(raw ?? "").trim();
  if (!text) return "Approver";
  if ((APPROVAL_ROLES as readonly string[]).includes(text)) return text;
  const formatted = formatTenantRole(text);
  return formatted || text;
}

function effectiveStepRole(step: ApprovalChainStep): string {
  return String(step.escalated_to_role || step.role || "").trim();
}

export function approvalChainRequired(chain: ApprovalChain | null | undefined): number {
  const docs = documentSteps(chain);
  if (docs.length > 0) return docs.length;
  const n = Number(chain?.required ?? 0);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function approvalChainRecorded(chain: ApprovalChain | null | undefined): number {
  const docs = documentSteps(chain);
  if (docs.length > 0) {
    return docs.filter((s) => s.status === "approved").length;
  }
  const approvals = chain?.approvals ?? [];
  const ids = new Set(
    approvals.map((a) => a.user_id).filter((id) => id != null && Number.isFinite(Number(id)))
  );
  return ids.size;
}

export function approvalChainQuorumMet(chain: ApprovalChain | null | undefined): boolean {
  const required = approvalChainRequired(chain);
  if (required <= 0) return false;
  return approvalChainRecorded(chain) >= required;
}

export function approvalChainCurrentStepRole(
  chain: ApprovalChain | null | undefined
): string | null {
  if (chain?.current_step_role) {
    return approvalRoleLabel(chain.current_step_role);
  }
  for (const step of documentSteps(chain)) {
    if (step.status !== "approved") {
      const role = effectiveStepRole(step);
      return role ? approvalRoleLabel(role) : null;
    }
  }
  return null;
}

export function approvalChainProgressLabel(
  chain: ApprovalChain | null | undefined
): string | null {
  const required = approvalChainRequired(chain);
  if (required <= 0) return null;
  const recorded = approvalChainRecorded(chain);
  const awaiting = approvalChainCurrentStepRole(chain);
  if (awaiting && recorded < required) {
    return `${recorded} of ${required} · awaiting ${awaiting}`;
  }
  return `${recorded} of ${required} approved`;
}

export function approvalChainToApproverSteps(
  chain: ApprovalChain | null | undefined
): ApproverStep[] {
  const docs = documentSteps(chain);
  if (docs.length > 0) {
    return docs.map((step, i) => {
      const requiredRole = approvalRoleLabel(step.role);
      const escalated = step.escalated_to_role
        ? approvalRoleLabel(step.escalated_to_role)
        : null;
      const roleLabel =
        step.status === "approved"
          ? requiredRole
          : escalated
            ? `${requiredRole} → ${escalated}`
            : requiredRole;
      const approvedName =
        step.name?.trim() ||
        (step.user_id != null ? `User ${step.user_id}` : null);
      return {
        id: String(step.key || (step.index ?? i)),
        name:
          step.status === "approved"
            ? approvedName || requiredRole
            : escalated
              ? `Awaiting ${escalated}`
              : `Awaiting ${requiredRole}`,
        role: roleLabel,
        state:
          step.status === "approved"
            ? ("approved" as const)
            : step.status === "rejected"
              ? ("rejected" as const)
              : ("pending" as const),
        ts: step.at ?? undefined,
      };
    });
  }

  const approvals = chain?.approvals ?? [];
  const required = approvalChainRequired(chain);
  const steps: ApproverStep[] = approvals.map((a: ApprovalChainEntry) => ({
    id: String(a.user_id),
    name: a.name || `User ${a.user_id}`,
    role: approvalRoleLabel(a.role),
    state: "approved" as const,
    ts: a.at,
  }));
  const pendingSlots = Math.max(0, required - steps.length);
  for (let i = 0; i < pendingSlots; i++) {
    steps.push({
      id: `pending-${i}`,
      name: "Awaiting",
      role: "Approver",
      state: "pending",
    });
  }
  return steps;
}

export function invoiceHasPendingQuorum(inv: Invoice): boolean {
  const chain = inv.approval_chain;
  if (!chain || approvalChainRequired(chain) <= 0) return false;
  return !approvalChainQuorumMet(chain);
}
