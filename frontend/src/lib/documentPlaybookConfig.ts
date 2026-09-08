/** Playbook profile catalogue — align with backend playbook_profile_catalog.py */

import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { defaultCounterpartyTypeForRoute } from "@/lib/v5DocumentTypes";
import {
  bundleMandatoryMatchesSuggested,
  normalizeDtCodeList,
  playbookEnforcesBundle,
  reconcileBundleDraft,
} from "@/lib/documentBundleConfig";
import {
  derivePostingFromKlassAndProfile,
  isTransPosting,
} from "@/lib/documentTypeKlass";
import { defaultPlaybookProfileForCode as shippedDefaultPlaybookProfileForCode } from "@/lib/documentTypePlaybookDefaults";
import { reconcileTeamExpenseKindForDocumentType } from "@/lib/teamExpenseKind";

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
  | "two_way_so_invoice"
  | "two_way_dn_invoice"
  | "two_way_grn_invoice"
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
  autoApproveBelow?: number | null;
  requireApprovalForUnmatched?: boolean;
  requireApprovalForUnverifiedCounterparty?: boolean;
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
  { value: "two_way_so_invoice", label: "2-way SO ↔ Invoice" },
  { value: "two_way_dn_invoice", label: "2-way DN ↔ Invoice" },
  { value: "two_way_grn_invoice", label: "2-way GRN ↔ Invoice" },
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
    | "code"
    | "klass"
    | "posting"
    | "purchaseBundleRole"
    | "salesBundleRole"
    | "playbookProfile"
    | "matrixTemplateCode"
  >
): PlaybookProfile {
  const purchaseRole = (docType.purchaseBundleRole || "").trim().toLowerCase();
  if (purchaseRole === "po" || purchaseRole === "grn") return "supporting";
  const salesRole = (docType.salesBundleRole || "").trim().toLowerCase();
  if (salesRole === "so" || salesRole === "dn") return "supporting";
  const explicit = (docType.playbookProfile || "").trim().toLowerCase() as PlaybookProfile;
  if (explicit) return explicit;
  const catalogueCode = (docType.matrixTemplateCode || docType.code || "").trim().toUpperCase();
  if (catalogueCode) {
    const defaultProfile = shippedDefaultPlaybookProfileForCode(catalogueCode);
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
  return {
    mode: "touchless_on_clean_match",
    autoApproveBelow: null,
    requireApprovalForUnmatched: false,
    requireApprovalForUnverifiedCounterparty: false,
  };
}

export function mergeApprovalPolicyMode(
  existing: ApprovalPolicy | undefined,
  mode: ApprovalMode
): ApprovalPolicy {
  return {
    autoApproveBelow: existing?.autoApproveBelow ?? null,
    requireApprovalForUnmatched: existing?.requireApprovalForUnmatched ?? false,
    requireApprovalForUnverifiedCounterparty:
      existing?.requireApprovalForUnverifiedCounterparty ?? false,
    mode,
  };
}

const ROUTE_PURCHASE = "Purchase Management";
const ROUTE_SALES = "Sales Management";

const ROUTE_UNIVERSAL_MATCH_MODES: MatchMode[] = [
  "none",
  "reference_invoice",
  "shipment",
  "subledger_reconcile",
  "receipt_line",
];

const ROUTE_PURCHASE_MATCH_MODES: MatchMode[] = [
  ...ROUTE_UNIVERSAL_MATCH_MODES,
  "three_way_po_grn",
  "two_way_po_ses",
  "two_way_grn_invoice",
];

const ROUTE_SALES_MATCH_MODES: MatchMode[] = [
  ...ROUTE_UNIVERSAL_MATCH_MODES,
  "three_way_so_dn",
  "two_way_so_invoice",
  "two_way_dn_invoice",
];

const TWO_WAY_MATCH_MODES = new Set<MatchMode>([
  "two_way_po_ses",
  "two_way_so_invoice",
  "two_way_dn_invoice",
  "two_way_grn_invoice",
]);
const THREE_WAY_MATCH_MODES = new Set<MatchMode>(["three_way_po_grn", "three_way_so_dn"]);

export function isTwoWayMatchMode(matchMode?: string | null): boolean {
  return TWO_WAY_MATCH_MODES.has((matchMode ?? "").trim().toLowerCase() as MatchMode);
}

export function isThreeWayMatchMode(matchMode?: string | null): boolean {
  return THREE_WAY_MATCH_MODES.has((matchMode ?? "").trim().toLowerCase() as MatchMode);
}

export function isSalesManagementRoute(routeTarget?: string | null): boolean {
  return (routeTarget ?? "").trim() === ROUTE_SALES;
}

export function isPurchaseManagementRoute(routeTarget?: string | null): boolean {
  return (routeTarget ?? "").trim() === ROUTE_PURCHASE;
}

export function normalizeMatchMode(mode: string | undefined, fallback: MatchMode): MatchMode {
  const token = (mode || "").trim().toLowerCase();
  if (MATCH_MODE_OPTIONS.some((row) => row.value === token)) {
    return token as MatchMode;
  }
  return fallback;
}

export function normalizeApprovalMode(mode: string | undefined, fallback: ApprovalMode): ApprovalMode {
  const token = (mode || "").trim().toLowerCase();
  if (APPROVAL_MODE_OPTIONS.some((row) => row.value === token)) {
    return token as ApprovalMode;
  }
  return fallback;
}

/** Match modes valid for the workspace route (sales/purchase restrict PO vs SO matching). */
export function matchModesForRoute(routeTarget?: string | null): MatchMode[] {
  if (isPurchaseManagementRoute(routeTarget)) {
    return ROUTE_PURCHASE_MATCH_MODES;
  }
  if (isSalesManagementRoute(routeTarget)) {
    return ROUTE_SALES_MATCH_MODES;
  }
  return MATCH_MODE_OPTIONS.map((row) => row.value);
}

export function clampMatchModeForRoute(
  routeTarget: string | undefined | null,
  mode: MatchMode
): MatchMode {
  if (matchModeAllowedForRoute(routeTarget, mode)) return mode;
  return "none";
}

export function playbookProfileForBundleRole(
  draft: Pick<DocumentTypeDefinition, "purchaseBundleRole" | "salesBundleRole">
): PlaybookProfile | null {
  const purchaseRole = (draft.purchaseBundleRole || "").trim().toLowerCase();
  if (purchaseRole === "po" || purchaseRole === "grn") return "supporting";
  const salesRole = (draft.salesBundleRole || "").trim().toLowerCase();
  if (salesRole === "so" || salesRole === "dn") return "supporting";
  return null;
}

export function reconcilePlaybookDraft(draft: DocumentTypeDefinition): DocumentTypeDefinition {
  const bundleProfile = playbookProfileForBundleRole(draft);
  if (bundleProfile) {
    const preset = playbookPresetForProfile(bundleProfile);
    return {
      ...draft,
      playbookProfile: bundleProfile,
      matchPolicy: { mode: preset.matchMode },
      approvalPolicy: mergeApprovalPolicyMode(draft.approvalPolicy, preset.approvalMode),
    };
  }

  let profile = (draft.playbookProfile || "").trim().toLowerCase() as PlaybookProfile;
  if (!profile || !(profile in PROFILE_PRESETS)) {
    profile = inferPlaybookProfileFromDefinition(draft);
  }

  const preset = playbookPresetForProfile(profile);
  const matchMode = clampMatchModeForRoute(
    draft.routeTarget,
    normalizeMatchMode(draft.matchPolicy?.mode, preset.matchMode)
  );
  const approvalMode = normalizeApprovalMode(draft.approvalPolicy?.mode, preset.approvalMode);

  return {
    ...draft,
    playbookProfile: profile,
    matchPolicy: { mode: matchMode },
    approvalPolicy: mergeApprovalPolicyMode(draft.approvalPolicy, approvalMode),
  };
}

export function applyPlaybookProfileSelection(
  draft: DocumentTypeDefinition,
  profile: PlaybookProfile
): DocumentTypeDefinition {
  const preset = playbookPresetForProfile(profile);
  return {
    ...draft,
    playbookProfile: profile,
    matchPolicy: { mode: clampMatchModeForRoute(draft.routeTarget, preset.matchMode) },
    approvalPolicy: mergeApprovalPolicyMode(draft.approvalPolicy, preset.approvalMode),
  };
}

/** Apply playbook profile change and reconcile supporting document requirements. */
export function applyPlaybookChange(
  draft: DocumentTypeDefinition,
  profile: PlaybookProfile,
  documentTypes?: DocumentTypeDefinition[]
): DocumentTypeDefinition {
  const previous = draft;
  const hadEnforce = playbookEnforcesBundle(previous);
  let next = applyPlaybookProfileSelection(draft, profile);
  let preservedMandatory: string[] | null = null;

  if (hadEnforce && !playbookEnforcesBundle(next) && documentTypes?.length) {
    if (bundleMandatoryMatchesSuggested(previous, documentTypes)) {
      next = { ...next, bundleMandatory: [], bundleConditional: [] };
    } else {
      const mandatory = normalizeDtCodeList(previous.bundleMandatory);
      if (mandatory.length > 0) {
        preservedMandatory = mandatory;
      }
    }
  }

  next = reconcilePlaybookDraft(next);
  next = reconcileBundleDraft(next, documentTypes);

  if (preservedMandatory && !playbookEnforcesBundle(next)) {
    next = { ...next, bundleMandatory: preservedMandatory };
  }

  return next;
}

export function reconcileDocumentTypeDraft(
  draft: DocumentTypeDefinition,
  documentTypes?: DocumentTypeDefinition[]
): DocumentTypeDefinition {
  const reconciled = reconcileBundleDraft(reconcilePlaybookDraft(draft), documentTypes);
  if ((reconciled.routeTarget || "").trim() !== "Team Expenses") {
    return reconciled;
  }
  const teamExpenseKind = reconcileTeamExpenseKindForDocumentType({
    title: reconciled.title,
    shortTitle: reconciled.shortTitle,
    configured: reconciled.teamExpenseKind,
  });
  if (teamExpenseKind === (reconciled.teamExpenseKind || "")) {
    return reconciled;
  }
  return { ...reconciled, teamExpenseKind: teamExpenseKind as DocumentTypeDefinition["teamExpenseKind"] };
}

export function applyRoutePlaybookAndBundleDefaults(
  draft: DocumentTypeDefinition,
  nextRoute: string,
  documentTypes?: DocumentTypeDefinition[]
): DocumentTypeDefinition {
  return reconcileDocumentTypeDraft(applyRoutePlaybookDefaults(draft, nextRoute), documentTypes);
}

export function playbookProfileOptionsForEditor(draft: DocumentTypeDefinition) {
  const current = effectivePlaybookProfile(draft);
  const routeAllowed = new Set(playbookProfilesForRoute(draft.routeTarget));
  const options = PLAYBOOK_PROFILE_OPTIONS.filter((row) => routeAllowed.has(row.value));
  if (routeAllowed.has(current)) return options;
  return [
    ...options,
    { value: current, label: `${playbookProfileLabel(current)} (current)` },
  ];
}

export function matchModeOptionsForEditor(draft: DocumentTypeDefinition) {
  const current = effectiveMatchPolicy(draft).mode;
  const allowed = new Set(matchModesForRoute(draft.routeTarget));
  const options = MATCH_MODE_OPTIONS.filter((row) => allowed.has(row.value));
  if (allowed.has(current)) return options;
  return [...options, { value: current, label: `${matchModeLabel(current)} (current)` }];
}

export function isProfilePresetMatchRouteIncompatible(
  draft: DocumentTypeDefinition
): boolean {
  const profile = effectivePlaybookProfile(draft);
  const presetMatch = playbookPresetForProfile(profile).matchMode;
  return !matchModeAllowedForRoute(draft.routeTarget, presetMatch);
}

export function matchModeAllowedForRoute(
  routeTarget: string | undefined | null,
  matchMode: string | undefined | null
): boolean {
  const token = (matchMode ?? "").trim().toLowerCase() as MatchMode;
  return matchModesForRoute(routeTarget).includes(token);
}

export function suggestedPlaybookForRoute(routeTarget?: string | null): PlaybookProfile {
  if (isSalesManagementRoute(routeTarget)) return "ar_goods";
  if (isPurchaseManagementRoute(routeTarget)) return "po_goods";
  return "standard_transactional";
}

/** Playbook profiles whose preset match mode is valid on this workspace route. */
export function playbookProfilesForRoute(routeTarget?: string | null): PlaybookProfile[] {
  const allowed = new Set(matchModesForRoute(routeTarget));
  return PLAYBOOK_PROFILE_OPTIONS.map((row) => row.value).filter((profile) =>
    allowed.has(playbookPresetForProfile(profile).matchMode)
  );
}

export function matchModeOptionsForRoute(routeTarget?: string | null) {
  const allowed = new Set(matchModesForRoute(routeTarget));
  return MATCH_MODE_OPTIONS.filter((row) => allowed.has(row.value));
}

/** Invoice drawer / dossier tab label from route + effective match mode. */
export function matchTabLabel(
  routeTarget?: string | null,
  matchMode?: string | null
): string {
  const mode = (matchMode ?? "").trim().toLowerCase();
  if (mode === "two_way_so_invoice") return "2-way match (SO · Invoice)";
  if (mode === "two_way_dn_invoice") return "2-way match (DN · Invoice)";
  if (mode === "two_way_grn_invoice") return "2-way match (GRN · Invoice)";
  if (mode === "two_way_po_ses") {
    return isPurchaseManagementRoute(routeTarget)
      ? "2-way match (PO · Invoice)"
      : "2-way match (PO · service entry)";
  }
  if (isSalesManagementRoute(routeTarget)) {
    return isTwoWayMatchMode(matchMode)
      ? "2-way match"
      : "3-way match (SO · DN · Invoice)";
  }
  if (isPurchaseManagementRoute(routeTarget)) {
    return isTwoWayMatchMode(matchMode)
      ? "2-way match"
      : "3-way match (PO · GRN · Invoice)";
  }
  return isTwoWayMatchMode(matchMode) ? "2-way match" : "3-way match";
}

/** When workspace route changes, align playbook if current match mode is incompatible. */
export function applyRoutePlaybookDefaults(
  draft: DocumentTypeDefinition,
  nextRoute: string
): DocumentTypeDefinition {
  const withRoute: DocumentTypeDefinition = {
    ...draft,
    routeTarget: nextRoute,
    counterpartyType: defaultCounterpartyTypeForRoute(nextRoute),
    // Claim kind is meaningless off the Team Expenses route; leaving it set would
    // silently reapply if the type is routed back later.
    teamExpenseKind: nextRoute === "Team Expenses" ? draft.teamExpenseKind : "",
  };
  const currentMode = effectiveMatchPolicy(withRoute).mode;
  if (matchModeAllowedForRoute(nextRoute, currentMode)) {
    return reconcilePlaybookDraft(withRoute);
  }
  const profile = suggestedPlaybookForRoute(nextRoute);
  const preset = playbookPresetForProfile(profile);
  return reconcilePlaybookDraft({
    ...withRoute,
    playbookProfile: profile,
    matchPolicy: { mode: preset.matchMode },
    approvalPolicy: { mode: preset.approvalMode },
  });
}
