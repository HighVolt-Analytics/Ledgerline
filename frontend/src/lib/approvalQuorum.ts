import type { ApprovalChain, ApprovalChainEntry, Invoice } from "@/api/types";
import type { ApproverStep } from "@/lib/v4MockData";
import { formatTenantRole } from "@/lib/tenantRoles";

export function approvalChainRequired(chain: ApprovalChain | null | undefined): number {
  const n = Number(chain?.required ?? 0);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function approvalChainRecorded(chain: ApprovalChain | null | undefined): number {
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

export function approvalChainProgressLabel(
  chain: ApprovalChain | null | undefined
): string | null {
  const required = approvalChainRequired(chain);
  if (required <= 0) return null;
  const recorded = approvalChainRecorded(chain);
  return `${recorded} of ${required} approved`;
}

export function approvalChainToApproverSteps(
  chain: ApprovalChain | null | undefined
): ApproverStep[] {
  const approvals = chain?.approvals ?? [];
  const required = approvalChainRequired(chain);
  const steps: ApproverStep[] = approvals.map((a: ApprovalChainEntry) => ({
    id: String(a.user_id),
    name: a.name || `User ${a.user_id}`,
    role: formatTenantRole(a.role),
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
