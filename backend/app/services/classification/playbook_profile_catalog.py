"""Playbook profile presets — match, approval, and bundle behaviour per DT family."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.playbook_policy import (
    ApprovalMode,
    ApprovalPolicy,
    MatchMode,
    MatchPolicy,
    PlaybookProfile,
)

PROFILE_PO_GOODS: PlaybookProfile = "po_goods"
PROFILE_AR_GOODS: PlaybookProfile = "ar_goods"
PROFILE_AR_GOODS_2WAY: PlaybookProfile = "ar_goods_2way"
PROFILE_PO_SERVICES: PlaybookProfile = "po_services"
PROFILE_DIRECT_EXPENSE: PlaybookProfile = "direct_expense"
PROFILE_CREDIT_ADJUSTMENT: PlaybookProfile = "credit_adjustment"
PROFILE_DEBIT_NOTE: PlaybookProfile = "debit_note"
PROFILE_PRE_TRANSACTIONAL: PlaybookProfile = "pre_transactional"
PROFILE_IMPORT_DOSSIER: PlaybookProfile = "import_dossier"
PROFILE_FREIGHT_LOGISTICS: PlaybookProfile = "freight_logistics"
PROFILE_INTERCOMPANY: PlaybookProfile = "intercompany"
PROFILE_EMPLOYEE_CLAIM: PlaybookProfile = "employee_claim"
PROFILE_RECONCILIATION: PlaybookProfile = "reconciliation"
PROFILE_SUPPORTING: PlaybookProfile = "supporting"
PROFILE_INFORMATIONAL: PlaybookProfile = "informational"
PROFILE_MASTER_DATA: PlaybookProfile = "master_data"
PROFILE_NON_ACTIONABLE: PlaybookProfile = "non_actionable"
PROFILE_COMPLIANCE_ROUTE: PlaybookProfile = "compliance_route"
PROFILE_STANDARD_TRANSACTIONAL: PlaybookProfile = "standard_transactional"


@dataclass(frozen=True)
class PlaybookProfilePreset:
    match_mode: MatchMode
    approval_mode: ApprovalMode
    enforce_bundle_mandatory: bool


PROFILE_PRESETS: dict[PlaybookProfile, PlaybookProfilePreset] = {
    PROFILE_PO_GOODS: PlaybookProfilePreset(
        match_mode="three_way_po_grn",
        approval_mode="touchless_on_clean_match",
        enforce_bundle_mandatory=True,
    ),
    PROFILE_AR_GOODS: PlaybookProfilePreset(
        match_mode="three_way_so_dn",
        approval_mode="touchless_on_clean_match",
        enforce_bundle_mandatory=True,
    ),
    PROFILE_AR_GOODS_2WAY: PlaybookProfilePreset(
        match_mode="two_way_dn_invoice",
        approval_mode="supervisor_on_exception",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_PO_SERVICES: PlaybookProfilePreset(
        match_mode="two_way_po_ses",
        approval_mode="touchless_on_clean_match",
        enforce_bundle_mandatory=True,
    ),
    PROFILE_DIRECT_EXPENSE: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="full_doa",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_CREDIT_ADJUSTMENT: PlaybookProfilePreset(
        match_mode="reference_invoice",
        approval_mode="supervisor_on_exception",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_DEBIT_NOTE: PlaybookProfilePreset(
        match_mode="reference_invoice",
        approval_mode="never_touchless",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_PRE_TRANSACTIONAL: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="full_doa",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_IMPORT_DOSSIER: PlaybookProfilePreset(
        match_mode="shipment",
        approval_mode="never_touchless",
        enforce_bundle_mandatory=True,
    ),
    PROFILE_FREIGHT_LOGISTICS: PlaybookProfilePreset(
        match_mode="shipment",
        approval_mode="supervisor_on_exception",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_INTERCOMPANY: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="full_doa",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_EMPLOYEE_CLAIM: PlaybookProfilePreset(
        match_mode="receipt_line",
        approval_mode="manager_gate",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_RECONCILIATION: PlaybookProfilePreset(
        match_mode="subledger_reconcile",
        approval_mode="no_posting",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_SUPPORTING: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="no_posting",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_INFORMATIONAL: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="no_posting",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_MASTER_DATA: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="never_touchless",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_NON_ACTIONABLE: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="no_posting",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_COMPLIANCE_ROUTE: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="no_posting",
        enforce_bundle_mandatory=False,
    ),
    PROFILE_STANDARD_TRANSACTIONAL: PlaybookProfilePreset(
        match_mode="none",
        approval_mode="touchless_on_clean_match",
        enforce_bundle_mandatory=False,
    ),
}


DEFAULT_PROFILE_BY_CODE: dict[str, PlaybookProfile] = {
    "DT-01": PROFILE_PO_GOODS,
    "DT-02": PROFILE_SUPPORTING,
    "DT-03": PROFILE_SUPPORTING,
    "DT-04": PROFILE_CREDIT_ADJUSTMENT,
    "DT-05": PROFILE_DEBIT_NOTE,
    "DT-06": PROFILE_PRE_TRANSACTIONAL,
    "DT-07": PROFILE_STANDARD_TRANSACTIONAL,
    "DT-08": PROFILE_DIRECT_EXPENSE,
    "DT-09": PROFILE_FREIGHT_LOGISTICS,
    "DT-10": PROFILE_IMPORT_DOSSIER,
    "DT-11": PROFILE_INTERCOMPANY,
    "DT-12": PROFILE_EMPLOYEE_CLAIM,
    "DT-13": PROFILE_RECONCILIATION,
    "DT-14": PROFILE_SUPPORTING,
    "DT-15": PROFILE_SUPPORTING,
    "DT-16": PROFILE_SUPPORTING,
    "DT-17": PROFILE_SUPPORTING,
    "DT-18": PROFILE_SUPPORTING,
    "DT-19": PROFILE_STANDARD_TRANSACTIONAL,
    "DT-20": PROFILE_STANDARD_TRANSACTIONAL,
    "DT-21": PROFILE_DIRECT_EXPENSE,
    "DT-22": PROFILE_INFORMATIONAL,
    "DT-23": PROFILE_MASTER_DATA,
    "DT-24": PROFILE_NON_ACTIONABLE,
    "DT-25": PROFILE_COMPLIANCE_ROUTE,
    "DT-26": PROFILE_AR_GOODS,
    "DT-27": PROFILE_SUPPORTING,
    "DT-28": PROFILE_SUPPORTING,
}

DEFAULT_COUNTERPARTY_SOURCE_BY_PLAYBOOK: dict[str, str] = {
    PROFILE_AR_GOODS: "consignee",
    PROFILE_AR_GOODS_2WAY: "consignee",
    PROFILE_FREIGHT_LOGISTICS: "consignee",
    PROFILE_IMPORT_DOSSIER: "consignee",
}


def effective_counterparty_source(defn: DocumentTypeDefinition) -> str:
    explicit = (defn.counterparty_source or "").strip().lower()
    if explicit:
        return explicit
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )

    profile = effective_playbook_profile(defn)
    return DEFAULT_COUNTERPARTY_SOURCE_BY_PLAYBOOK.get(profile, "letterhead")


def default_playbook_profile_for_code(code: str) -> PlaybookProfile:
    normalized = code.strip().upper()
    return DEFAULT_PROFILE_BY_CODE.get(normalized, PROFILE_STANDARD_TRANSACTIONAL)


def infer_playbook_profile_from_definition(definition: DocumentTypeDefinition) -> PlaybookProfile:
    from app.services.classification.document_type_klass import (
        derive_posting_from_klass_and_profile,
        is_trans_posting,
    )

    purchase_role = (definition.purchase_bundle_role or "").strip().lower()
    if purchase_role in {"po", "grn"}:
        return PROFILE_SUPPORTING
    sales_role = (definition.sales_bundle_role or "").strip().lower()
    if sales_role in {"so", "dn"}:
        return PROFILE_SUPPORTING
    explicit = (definition.playbook_profile or "").strip().lower()
    if explicit:
        return explicit  # type: ignore[return-value]
    code = (definition.code or "").strip().upper()
    if code:
        default = default_playbook_profile_for_code(code)
        if default != PROFILE_STANDARD_TRANSACTIONAL:
            return default
    posting = derive_posting_from_klass_and_profile(
        definition.klass,
        definition.playbook_profile,
        existing_posting=definition.posting,
    ).strip().lower()
    if posting == "down-payment":
        return PROFILE_PRE_TRANSACTIONAL
    if is_trans_posting(definition):
        return PROFILE_STANDARD_TRANSACTIONAL
    return PROFILE_SUPPORTING


def preset_for_profile(profile: str) -> PlaybookProfilePreset:
    token = (profile or PROFILE_STANDARD_TRANSACTIONAL).strip().lower()
    if token not in PROFILE_PRESETS:
        token = PROFILE_STANDARD_TRANSACTIONAL
    return PROFILE_PRESETS[token]  # type: ignore[index]
