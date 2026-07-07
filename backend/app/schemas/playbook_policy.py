"""Per document-type matching and approval policy configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MatchMode = Literal[
    "none",
    "three_way_po_grn",
    "three_way_so_dn",
    "two_way_po_ses",
    "two_way_so_invoice",
    "two_way_dn_invoice",
    "two_way_grn_invoice",
    "reference_invoice",
    "subledger_reconcile",
    "shipment",
    "receipt_line",
]

ApprovalMode = Literal[
    "no_posting",
    "touchless_on_clean_match",
    "full_doa",
    "supervisor_on_exception",
    "never_touchless",
    "manager_gate",
    "variance_workflow",
]

PlaybookProfile = Literal[
    "po_goods",
    "ar_goods",
    "ar_goods_2way",
    "po_services",
    "direct_expense",
    "credit_adjustment",
    "debit_note",
    "pre_transactional",
    "import_dossier",
    "freight_logistics",
    "intercompany",
    "employee_claim",
    "reconciliation",
    "supporting",
    "informational",
    "master_data",
    "non_actionable",
    "compliance_route",
    "standard_transactional",
]

KNOWN_MATCH_MODES = frozenset(
    {
        "none",
        "three_way_po_grn",
        "three_way_so_dn",
        "two_way_po_ses",
        "two_way_so_invoice",
        "two_way_dn_invoice",
        "two_way_grn_invoice",
        "reference_invoice",
        "subledger_reconcile",
        "shipment",
        "receipt_line",
    }
)

KNOWN_APPROVAL_MODES = frozenset(
    {
        "no_posting",
        "touchless_on_clean_match",
        "full_doa",
        "supervisor_on_exception",
        "never_touchless",
        "manager_gate",
        "variance_workflow",
    }
)

KNOWN_PLAYBOOK_PROFILES = frozenset(
    {
        "po_goods",
        "ar_goods",
        "ar_goods_2way",
        "po_services",
        "direct_expense",
        "credit_adjustment",
        "debit_note",
        "pre_transactional",
        "import_dossier",
        "freight_logistics",
        "intercompany",
        "employee_claim",
        "reconciliation",
        "supporting",
        "informational",
        "master_data",
        "non_actionable",
        "compliance_route",
        "standard_transactional",
    }
)


class MatchPolicy(BaseModel):
    mode: MatchMode = "none"
    qty_tolerance_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        alias="qtyTolerancePct",
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        token = str(value or "none").strip().lower()
        if token not in KNOWN_MATCH_MODES:
            return "none"
        return token


class ApprovalPolicy(BaseModel):
    mode: ApprovalMode = "touchless_on_clean_match"

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        token = str(value or "touchless_on_clean_match").strip().lower()
        if token not in KNOWN_APPROVAL_MODES:
            return "touchless_on_clean_match"
        return token


def normalize_match_policy(value: Any) -> MatchPolicy:
    if value is None:
        return MatchPolicy()
    if isinstance(value, MatchPolicy):
        return value
    if isinstance(value, dict):
        try:
            return MatchPolicy.model_validate(value)
        except Exception:
            return MatchPolicy()
    return MatchPolicy()


def normalize_approval_policy(value: Any) -> ApprovalPolicy:
    if value is None:
        return ApprovalPolicy()
    if isinstance(value, ApprovalPolicy):
        return value
    if isinstance(value, dict):
        try:
            return ApprovalPolicy.model_validate(value)
        except Exception:
            return ApprovalPolicy()
    return ApprovalPolicy()
