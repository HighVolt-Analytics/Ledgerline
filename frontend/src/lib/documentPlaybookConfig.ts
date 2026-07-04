/** Playbook profile catalogue — align with backend playbook_profile_catalog.py */

import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  derivePostingFromKlassAndProfile,
  isTransPosting,
} from "@/lib/documentTypeKlass";
import { defaultPlaybookProfileForCode as shippedDefaultPlaybookProfileForCode } from "@/lib/documentTypePlaybookDefaults";

export type PlaybookProfile =
  | "po_goods"
  | "ar_goods"
  | "ar_goods_2way"
  | "po_services"
  | "direct_expense"
  | "credit_adjustment"
  | "debit_note"
  | "pre_transactional"
  | "import_dossier"
  | "freight_logistics"
  | "intercompany"
  | "employee_claim"
  | "reconciliation"
  | "supporting"
  | "informational"
  | "master_data"
  | "non_actionable"
  | "compliance_route"
  | "standard_transactional";

export type MatchMode =
  | "none"
  | "three_way_po_grn"
  | "three_way_so_dn"
  | "two_way_po_ses"
  | "two_way_dn_invoice"
  | "reference_invoice"
  | "subledger_reconcile"
  | "shipment"
  | "receipt_line";

export type ApprovalMode =
  | "no_posting"
  | "touchless_on_clean_match"
  | "full_doa"
  | "supervisor_on_exception"
  | "never_touchless"
  | "manager_gate"
  | "variance_workflow";

export type MatchPolicy = {
  mode: MatchMode;
};

export type ApprovalPolicy = {
  mode: ApprovalMode;
};

export const PLAYBOOK_PROFILE_OPTIONS: Array<{ value: PlaybookProfile; label: string }> = [
  { value: "po_goods", label: "PO goods (3-way)" },
  { value: "ar_goods", label: "AR goods (3-way)" },
  { value: "ar_goods_2way", label: "AR goods (2-way DN)" },
  { value: "po_services", label: "PO services (2-way)" },
  { value: "direct_expense", label: "Direct expense" },
  { value: "credit_adjustment", label: "Credit / adjustment" },
  { value: "debit_note", label: "Debit note" },
  { value: "pre_transactional", label: "Pre-transactional" },
  { value: "import_dossier", label: "Import dossier" },
  { value: "freight_logistics", label: "Freight / logistics" },
  { value: "intercompany", label: "Intercompany" },
  { value: "employee_claim", label: "Employee claim" },
  { value: "reconciliation", label: "Reconciliation" },
  { value: "supporting", label: "Supporting document" },
  { value: "informational", label: "Informational" },
  { value: "master_data", label: "Master data" },
  { value: "non_actionable", label: "Non-actionable" },
  { value: "compliance_route", label: "Compliance route" },
  { value: "standard_transactional", label: "Standard transactional" },
];

export const MATCH_MODE_OPTIONS: Array<{ value: MatchMode; label: string }> = [
  { value: "none", label: "None" },
  { value: "three_way_po_grn", label: "3-way PO ↔ GRN ↔ Invoice" },
  { value: "three_way_so_dn", label: "3-way SO ↔ DN ↔ Invoice" },
  { value: "two_way_po_ses", label: "2-way PO ↔ service entry" },
  { value: "two_way_dn_invoice", label: "2-way DN ↔ Invoice" },
  { value: "reference_invoice", label: "Reference original invoice" },
  { value: "subledger_reconcile", label: "Subledger reconciliation" },
  { value: "shipment", label: "Shipment / logistics" },
  { value: "receipt_line", label: "Receipt per line" },
];

export const APPROVAL_MODE_OPTIONS: Array<{ value: ApprovalMode; label: string }> = [
  { value: "no_posting", label: "No posting" },
  { value: "touchless_on_clean_match", label: "Touchless when matched" },
  { value: "full_doa", label: "Full DOA approval" },
  { value: "supervisor_on_exception", label: "Supervisor on exception" },
  { value: "never_touchless", label: "Never touchless" },
  { value: "manager_gate", label: "Manager gate (team expenses)" },
  { value: "variance_workflow", label: "Variance workflow" },
];

export function inferPlaybookProfileFromDefinition(
  docType: Pick<
    DocumentTypeDefinition,
    "code" | "klass" | "posting" | "purchaseBundleRole" | "salesBundleRole" | "playbookProfile"
  >
): PlaybookProfile {
  const purchaseRole = (docType.purchaseBundleRole || "").trim().toLowerCase();
  if (purchaseRole === "po" || purchaseRole === "grn") return "supporting";
  const salesRole = (docType.salesBundleRole || "").trim().toLowerCase();
  if (salesRole === "so" || salesRole === "dn") return "supporting";
  const explicit = (docType.playbookProfile || "").trim().toLowerCase() as PlaybookProfile;
  if (explicit) return explicit;
  const code = (docType.code || "").trim().toUpperCase();
  if (code) {
    const defaultProfile = shippedDefaultPlaybookProfileForCode(code);
    if (defaultProfile !== "standard_transactional") return defaultProfile;
  }
  const posting = derivePostingFromKlassAndProfile(
    docType.klass,
    docType.playbookProfile,
    docType.posting
  )
    .trim()
    .toLowerCase();
  if (posting === "down-payment") return "pre_transactional";
  if (isTransPosting(docType)) return "standard_transactional";
  return "supporting";
}

const PROFILE_PRESETS: Record<
  PlaybookProfile,
  { matchMode: MatchMode; approvalMode: ApprovalMode; enforceBundle: boolean }
> = {
  po_goods: {
    matchMode: "three_way_po_grn",
    approvalMode: "touchless_on_clean_match",
    enforceBundle: true,
  },
  ar_goods: {
    matchMode: "three_way_so_dn",
    approvalMode: "touchless_on_clean_match",
    enforceBundle: true,
  },
  ar_goods_2way: {
    matchMode: "two_way_dn_invoice",
    approvalMode: "supervisor_on_exception",
    enforceBundle: false,
  },
  po_services: {
    matchMode: "two_way_po_ses",
    approvalMode: "touchless_on_clean_match",
    enforceBundle: true,
  },
  direct_expense: {
    matchMode: "none",
    approvalMode: "full_doa",
    enforceBundle: false,
  },
  credit_adjustment: {
    matchMode: "reference_invoice",
    approvalMode: "supervisor_on_exception",
    enforceBundle: false,
  },
  debit_note: {
    matchMode: "reference_invoice",
    approvalMode: "never_touchless",
    enforceBundle: false,
  },
  pre_transactional: {
    matchMode: "none",
    approvalMode: "full_doa",
    enforceBundle: false,
  },
  import_dossier: {
    matchMode: "shipment",
    approvalMode: "never_touchless",
    enforceBundle: true,
  },
  freight_logistics: {
    matchMode: "shipment",
    approvalMode: "supervisor_on_exception",
    enforceBundle: false,
  },
  intercompany: {
    matchMode: "none",
    approvalMode: "full_doa",
    enforceBundle: false,
  },
  employee_claim: {
    matchMode: "receipt_line",
    approvalMode: "manager_gate",
    enforceBundle: false,
  },
  reconciliation: {
    matchMode: "subledger_reconcile",
    approvalMode: "no_posting",
    enforceBundle: false,
  },
  supporting: {
    matchMode: "none",
    approvalMode: "no_posting",
    enforceBundle: false,
  },
  informational: {
    matchMode: "none",
    approvalMode: "no_posting",
    enforceBundle: false,
  },
  master_data: {
    matchMode: "none",
    approvalMode: "never_touchless",
    enforceBundle: false,
  },
  non_actionable: {
    matchMode: "none",
    approvalMode: "no_posting",
    enforceBundle: false,
  },
  compliance_route: {
    matchMode: "none",
    approvalMode: "no_posting",
    enforceBundle: false,
  },
  standard_transactional: {
    matchMode: "none",
    approvalMode: "touchless_on_clean_match",
    enforceBundle: false,
  },
};

export function playbookPresetForProfile(profile: PlaybookProfile) {
  return PROFILE_PRESETS[profile];
}

export function defaultPlaybookProfileForCode(
  code: string,
  docType?: Pick<
    DocumentTypeDefinition,
    "klass" | "posting" | "purchaseBundleRole" | "salesBundleRole" | "playbookProfile"
  >
): PlaybookProfile {
  if (docType) return inferPlaybookProfileFromDefinition({ ...docType, code });
  return shippedDefaultPlaybookProfileForCode(code);
}

export function effectivePlaybookProfile(docType: DocumentTypeDefinition): PlaybookProfile {
  const explicit = (docType.playbookProfile || "").trim().toLowerCase() as PlaybookProfile;
  if (explicit && explicit in PROFILE_PRESETS) return explicit;
  return inferPlaybookProfileFromDefinition(docType);
}

export function effectiveMatchPolicy(docType: DocumentTypeDefinition): MatchPolicy {
  if (docType.matchPolicy?.mode) return docType.matchPolicy;
  return { mode: PROFILE_PRESETS[effectivePlaybookProfile(docType)].matchMode };
}

export function effectiveApprovalPolicy(docType: DocumentTypeDefinition): ApprovalPolicy {
  if (docType.approvalPolicy?.mode) return docType.approvalPolicy;
  return { mode: PROFILE_PRESETS[effectivePlaybookProfile(docType)].approvalMode };
}

export function playbookSummary(docType: DocumentTypeDefinition): string {
  const profile = effectivePlaybookProfile(docType);
  const match = effectiveMatchPolicy(docType);
  const approval = effectiveApprovalPolicy(docType);
  const profileLabel =
    PLAYBOOK_PROFILE_OPTIONS.find((row) => row.value === profile)?.label ?? profile;
  const matchLabel =
    MATCH_MODE_OPTIONS.find((row) => row.value === match.mode)?.label ?? match.mode;
  const approvalLabel =
    APPROVAL_MODE_OPTIONS.find((row) => row.value === approval.mode)?.label ?? approval.mode;
  return `${profileLabel} · ${matchLabel} · ${approvalLabel}`;
}

export function matchModeLabel(mode: MatchMode): string {
  return MATCH_MODE_OPTIONS.find((row) => row.value === mode)?.label ?? mode;
}

export function approvalModeLabel(mode: ApprovalMode): string {
  return APPROVAL_MODE_OPTIONS.find((row) => row.value === mode)?.label ?? mode;
}

export function playbookProfileLabel(profile: PlaybookProfile): string {
  return PLAYBOOK_PROFILE_OPTIONS.find((row) => row.value === profile)?.label ?? profile;
}

export function emptyMatchPolicy(): MatchPolicy {
  return { mode: "none" };
}

export function emptyApprovalPolicy(): ApprovalPolicy {
  return { mode: "touchless_on_clean_match" };
}
