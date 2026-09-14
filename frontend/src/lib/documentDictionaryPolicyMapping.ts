/**
 * Maps industry-matrix dictionary labels → canonical playbook/match/approval enums.
 * Dictionary JSON stores human labels; adopt-time clone resolves to product slugs.
 */

import type { ApprovalMode, MatchMode, PlaybookProfile } from "@/lib/documentPlaybookConfig";

export type DictionaryEntryLike = {
  code: string;
  title: string;
  llmPrompt: string;
  posting: string;
  routeTarget: string;
  counterpartyType: string;
  playbookProfile: string;
  matchMode: string;
  approvalMode: string;
};

export const PLAYBOOK_PROFILE_BY_LABEL: Record<string, PlaybookProfile> = {
  "AP Invoice - classify goods/services (proposed)": "standard_transactional",
  "AR Services (proposed)": "ar_goods",
  "Advance / Subscription Billing (proposed)": "standard_transactional",
  "Agent Commission (proposed)": "direct_expense",
  "Bank Reconciliation (proposed)": "reconciliation",
  "Capex Purchase (proposed)": "po_goods",
  "Care Service Claim (proposed)": "standard_transactional",
  "Construction AP (proposed)": "standard_transactional",
  "Construction Progress Claim (proposed)": "standard_transactional",
  "Contract Variation (proposed)": "pre_transactional",
  "Contractor Services (proposed)": "po_services",
  "Credit Adjustment (proposed)": "credit_adjustment",
  "Employee Claim": "employee_claim",
  "Facility Costs (proposed)": "direct_expense",
  "Financial Service Fee (proposed)": "direct_expense",
  "Freight Cost (proposed)": "freight_logistics",
  "Fuel Purchase (proposed)": "direct_expense",
  "Funding Claim (proposed)": "direct_expense",
  "Grant Disbursement (proposed)": "direct_expense",
  "Healthcare Payer Claim (proposed)": "standard_transactional",
  "Investment Statement Support (proposed)": "informational",
  "Lease / Hire (proposed)": "direct_expense",
  "Network Goods / Services (proposed)": "standard_transactional",
  "PO Goods (3-way)": "po_goods",
  "PO Goods (3-way) / service PO as applicable": "po_goods",
  "Property Management Fee (proposed)": "direct_expense",
  "Recurring Bill (proposed)": "direct_expense",
  "Refund Request (proposed)": "credit_adjustment",
  "Rental Billing (proposed)": "standard_transactional",
  "Repairs / Maintenance (proposed)": "po_services",
  "Retention Release (proposed)": "standard_transactional",
  "Royalty Assessment (proposed)": "direct_expense",
  "Settlement Reconciliation (proposed)": "reconciliation",
  "Timesheet Support (proposed)": "supporting",
  "Toll Statement (proposed)": "reconciliation",
};

export const MATCH_MODE_BY_LABEL: Record<string, MatchMode> = {
  "3-way PO - GRN - Invoice": "three_way_po_grn",
  "Agency agreement + eligible enrolment/deal + commission calculation": "two_way_so_invoice",
  "Approved PO + actual receipt/inspection": "two_way_grn_invoice",
  "Approved agreement + service evidence + claim/invoice register": "two_way_po_ses",
  "Approved award + milestone/conditions + payee + bank execution": "none",
  "Approved capex PO + receipt/commissioning + invoice": "three_way_po_grn",
  "Bank transactions + cash ledger + open AP/AR items": "subledger_reconcile",
  "Carrier contract/rate + shipment/delivery + invoice": "shipment",
  "Contract + certified progress + cumulative billing register": "two_way_po_ses",
  "Contract retention ledger + release/defects certificate": "reference_invoice",
  "Contract/rate plan + service period/usage": "two_way_po_ses",
  "Customer contract/SO + service or delivery evidence": "three_way_so_dn",
  "Employee/contract + approved hours + payroll/billing run": "two_way_po_ses",
  "Engagement/PO + timesheet or deliverable acceptance": "two_way_po_ses",
  "Engagement/custody agreement + fee basis/period + invoice": "two_way_po_ses",
  "Enrolment/subscription contract + billing and delivery schedule": "two_way_so_invoice",
  "Executed agreement + lease schedule + invoice": "two_way_po_ses",
  "Executed lease + rent schedule + billing period": "reference_invoice",
  "Executed licence / statutory assessment + production/sales basis": "none",
  "Facility contract/PO + premises/service-period evidence": "two_way_po_ses",
  "Fuel receipt/card account + vehicle/equipment usage": "receipt_line",
  "Funding agreement + eligibility/milestones + claim register": "two_way_po_ses",
  "Goods: PO - GRN - invoice; services: PO/contract + acceptance": "three_way_po_grn",
  "Management agreement + rent/fee calculation + invoice": "two_way_so_invoice",
  "None at issue; link to later receipt/invoice matching": "none",
  "Original contract + authorised scope/price variation": "reference_invoice",
  "Original invoice + return/price adjustment evidence": "reference_invoice",
  "Original invoice/payment + refund entitlement + customer record": "reference_invoice",
  "PO/contract + equipment receipt or service acceptance": "three_way_po_grn",
  "Receipt per line + employee/advance record": "receipt_line",
  "Sales/POS batches + merchant settlement + bank receipt": "subledger_reconcile",
  "Subcontract + approved work/progress certificate + invoice": "two_way_po_ses",
  "Toll trips + vehicle account + prior invoice/payment records": "reference_invoice",
  "Trade confirmations + investment ledger + bank/custody records": "subledger_reconcile",
  "Work order + service completion + invoice": "two_way_po_ses",
};

export const APPROVAL_MODE_BY_LABEL: Record<string, ApprovalMode> = {
  "Authorised grant delegate + independent payment approver": "full_doa",
  "Budget owner + Finance, per approval matrix": "full_doa",
  "Budget owner + Finance; touchless only under approved recurring policy":
    "touchless_on_clean_match",
  "Budget owner, per purchase delegation, before issue": "full_doa",
  "Capex delegate + Finance, per approval matrix": "full_doa",
  "Finance + royalty/tax specialist as needed": "full_doa",
  "Finance lease review + delegated budget approval": "full_doa",
  "Finance preparer + independent reconciler": "supervisor_on_exception",
  "Finance reconciler; exceptions independently approved": "supervisor_on_exception",
  "Finance; billing approval per delegated matrix": "full_doa",
  "Finance; commercial owner where required": "full_doa",
  "Funding owner + Finance": "full_doa",
  "Independent refund delegate + Finance before credit/payment": "full_doa",
  "Investment accountant; independent reconciliation review": "supervisor_on_exception",
  "Line/project manager; Payroll/Finance reviews downstream posting": "supervisor_on_exception",
  "Manager + Finance, per approval matrix; no self-approval": "manager_gate",
  "Matched approved PO: touchless only under configured policy; exceptions to Finance":
    "touchless_on_clean_match",
  "Project/commercial delegate + Finance": "full_doa",
  "Service/contract owner + Finance": "full_doa",
  "Warehouse/requester confirms receipt; Finance reviews mismatch": "supervisor_on_exception",
};

const ROUTE_TARGETS = new Set([
  "Purchase Management",
  "Sales Management",
  "Expenses Management",
  "Team Expenses",
  "Vault",
]);

const COUNTERPARTY_TYPES = new Set(["vendor", "customer", "employee", "none"]);

export type DictionaryValidationIssue = {
  code: string;
  field: string;
  message: string;
};

export function resolvePlaybookProfileFromDictionary(entry: DictionaryEntryLike): PlaybookProfile {
  const label = entry.playbookProfile.trim();
  const mapped = PLAYBOOK_PROFILE_BY_LABEL[label];
  if (mapped) return mapped;
  if ((entry.posting || "").trim().toLowerCase() === "no") {
    return "supporting";
  }
  if (entry.routeTarget === "Team Expenses") return "employee_claim";
  if (entry.routeTarget === "Sales Management") return "ar_goods";
  return "standard_transactional";
}

export function resolveMatchModeFromDictionary(entry: DictionaryEntryLike): MatchMode {
  const mapped = MATCH_MODE_BY_LABEL[entry.matchMode.trim()];
  if (mapped) return mapped;
  if ((entry.posting || "").trim().toLowerCase() === "no") return "none";
  if (entry.routeTarget === "Sales Management") return "two_way_so_invoice";
  if (entry.routeTarget === "Team Expenses") return "receipt_line";
  return "none";
}

export function resolveApprovalModeFromDictionary(entry: DictionaryEntryLike): ApprovalMode {
  const mapped = APPROVAL_MODE_BY_LABEL[entry.approvalMode.trim()];
  if (mapped) return mapped;
  if ((entry.posting || "").trim().toLowerCase() === "no") return "no_posting";
  return "full_doa";
}

export function validateDictionaryEntries(entries: DictionaryEntryLike[]): DictionaryValidationIssue[] {
  const issues: DictionaryValidationIssue[] = [];
  const seenCodes = new Set<string>();

  for (const entry of entries) {
    const code = entry.code.trim().toUpperCase();
    if (!code) {
      issues.push({ code: "", field: "code", message: "Missing dictionary code" });
      continue;
    }
    if (seenCodes.has(code)) {
      issues.push({ code, field: "code", message: "Duplicate dictionary code" });
    }
    seenCodes.add(code);

    if (!entry.title.trim()) {
      issues.push({ code, field: "title", message: "Missing title" });
    }
    if (!entry.llmPrompt.trim() || entry.llmPrompt.trim().length < 20) {
      issues.push({ code, field: "llmPrompt", message: "Prompt must be at least 20 characters" });
    }
    if (!ROUTE_TARGETS.has(entry.routeTarget)) {
      issues.push({ code, field: "routeTarget", message: `Unknown route: ${entry.routeTarget}` });
    }
    if (!COUNTERPARTY_TYPES.has(entry.counterpartyType)) {
      issues.push({
        code,
        field: "counterpartyType",
        message: `Unknown counterparty: ${entry.counterpartyType}`,
      });
    }
    if (!PLAYBOOK_PROFILE_BY_LABEL[entry.playbookProfile.trim()]) {
      issues.push({
        code,
        field: "playbookProfile",
        message: `Unmapped playbook label: ${entry.playbookProfile}`,
      });
    }
    if (!MATCH_MODE_BY_LABEL[entry.matchMode.trim()]) {
      issues.push({ code, field: "matchMode", message: `Unmapped match label: ${entry.matchMode}` });
    }
    if (!APPROVAL_MODE_BY_LABEL[entry.approvalMode.trim()]) {
      issues.push({
        code,
        field: "approvalMode",
        message: `Unmapped approval label: ${entry.approvalMode}`,
      });
    }
  }

  return issues;
}
