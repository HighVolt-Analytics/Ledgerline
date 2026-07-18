"""Dossier hero view API schemas — align with frontend dossiers.ts types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DossierPipelineCheckResponse(BaseModel):
    id: str
    label: str
    state: str
    detail: str | None = None
    rule_ref: str | None = None
    expected: str | None = None
    actual: str | None = None


class DossierPipelineEvidenceResponse(BaseModel):
    label: str
    ref: str


class DossierPipelineStepResponse(BaseModel):
    stage_id: str
    state: str
    detail: str
    at: str | None = None
    actor: str | None = None
    duration_ms: int | None = None
    exception_code: str | None = None
    failure_reason: str | None = None
    remediation: str | None = None
    blocked_reason: str | None = None
    checks: list[DossierPipelineCheckResponse] = Field(default_factory=list)
    evidence: list[DossierPipelineEvidenceResponse] = Field(default_factory=list)


class DossierManualLinkInfoResponse(BaseModel):
    id: int
    invoice_id: int
    linked_dossier_id: str
    document_ref: str | None = None
    label: str
    document_type_code: str
    has_file: bool = False


class DossierManualLinkCreateRequest(BaseModel):
    linked_invoice_id: int
    slot_id: str | None = None


class DossierLinkedDocumentResponse(BaseModel):
    id: str
    document_type_code: str
    label: str
    document_ref: str | None = None
    invoice_no: str | None = None
    counterparty: str | None = None
    present: bool
    requirement: str
    purchase_bundle_role: str | None = None
    sales_bundle_role: str | None = None
    source: str | None = None
    linked_dossier_id: str | None = None
    invoice_id: int | None = None
    is_anchor: bool = False
    has_file: bool = False
    linkage_detail: str | None = None
    link_kind: str = "system"
    manual_link_id: int | None = None
    manual_link: DossierManualLinkInfoResponse | None = None


class DossierMatchSummaryResponse(BaseModel):
    status: str
    currency: str
    po_number: str | None = None
    po_qty: float | None = None
    po_unit_price: float | None = None
    po_value: float
    po_date: str | None = None
    grn_present: bool = False
    grn_qty: float | None = None
    grn_date: str | None = None
    grn_receiver: str | None = None
    grn_condition: str | None = None
    invoice_no: str | None = None
    invoice_qty: float | None = None
    invoice_unit_price: float | None = None
    invoice_value: float = 0.0
    invoice_gst: float = 0.0
    invoice_total: float
    qty_variance_value: float = 0.0
    price_variance_value: float = 0.0
    total_deviation: float = 0.0
    deviation: float = 0.0


class DossierLinkedDocumentsResponse(BaseModel):
    linkage_kind: str
    linkage_key: str | None = None
    linkage_label: str
    enforce_bundle: bool
    conditional_advisories: list[str] = Field(default_factory=list)
    documents: list[DossierLinkedDocumentResponse] = Field(default_factory=list)
    match_summary: DossierMatchSummaryResponse | None = None
    purchase_order_id: int | None = None
    sales_order_id: int | None = None


class DossierApprovalStepResponse(BaseModel):
    id: str
    kind: str
    label: str
    role: str
    actor: str
    state: str
    at: str | None = None
    detail: str | None = None
    policy_ref: str | None = None
    sod_note: str | None = None


class DossierApprovalChainResponse(BaseModel):
    policy_mode: str
    policy_label: str
    steps: list[DossierApprovalStepResponse] = Field(default_factory=list)


class DossierSummaryResponse(BaseModel):
    id: str
    invoice_id: int
    document_type_code: str
    document_type_title: str
    vendor: str
    counterparty_label: str = "Counterparty"
    route_target: str | None = None
    buyer: str
    invoice_ref: str
    capture_channel: str
    invoice_date: str
    currency: str
    subtotal: float
    tax: float
    total: float
    classification_label: str
    classification_confidence: int
    po_reference: str | None = None
    so_reference: str | None = None
    linkage_reference: str | None = None
    sla_label: str
    sla_breached: bool = False
    owner: str
    outcome: str
    outcome_banner: str
    blocker_stage_id: str | None = None
    blocker_reason: str | None = None
    blocker_remediation: str | None = None
    pipeline_path: Literal["understood", "not_understood", "unknown"] = "unknown"
    pipeline: list[DossierPipelineStepResponse] = Field(default_factory=list)
    linked_documents: DossierLinkedDocumentsResponse
    approval_chain: DossierApprovalChainResponse
