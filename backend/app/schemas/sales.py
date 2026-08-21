"""Sales order and three-way match schemas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.dossier import DossierMatchSummaryResponse
from app.schemas.purchase import MatchAmountLine, ThreeWayMatchResult


class SalesOrderResponse(BaseModel):
    id: int
    so_number: str
    customer: str | None = None
    so_date: date | None = None
    item: str | None = None
    requestor: str | None = None
    so_qty: float
    so_unit_price: float
    dn_qty: float | None = None
    dn_date: date | None = None
    dn_shipper: str | None = None
    dn_condition: str | None = None
    invoice_id: int | None = None
    so_document_id: int | None = None
    dn_document_id: int | None = None
    invoice_no: str | None = None
    invoice_qty: float = 0
    invoice_unit_price: float = 0
    gst_rate: float | None = None
    variance_approved: bool = False
    variance_approval_chain: dict | None = None
    status: str
    three_way_match_status: str | None = None
    match: ThreeWayMatchResult
    match_mode: str = "three_way_so_dn"
    route_target: str | None = None
    evaluation_status: str | None = None
    matched_rule_ids: list[str] = Field(default_factory=list)
    matched_rule_name: str | None = None
    matched_gl: str | None = None
    ledger: str | None = None
    sub_ledger: str | None = None
    sales_rule_id: str | None = None
    currency: str = ""


class DeliveryNoteCreate(BaseModel):
    dn_qty: Decimal = Field(gt=0)
    dn_date: date | None = None
    shipper: str | None = None
    condition_note: str | None = None


class SalesDossierMember(BaseModel):
    role: str
    label: str
    invoice_id: int | None = None
    document_ref: str | None = None
    present: bool = False
    has_stored_file: bool = False
    is_current: bool = False


class SalesDossierResponse(BaseModel):
    so_reference: str | None = None
    current_role: str | None = None
    members: list[SalesDossierMember] = Field(default_factory=list)
    sales_order_id: int | None = None
    match: ThreeWayMatchResult | None = None
    match_status: str | None = None
    match_summary: DossierMatchSummaryResponse | None = None
    sales_register: SalesOrderResponse | None = None


class TwoWaySalesMatchResponse(BaseModel):
    """DN ↔ invoice match without a sales-order register row."""

    invoice_id: int
    dn_invoice_id: int | None = None
    invoice_no: str | None = None
    customer: str | None = None
    dn_qty: float | None = None
    invoice_qty: float = 0
    invoice_unit_price: float = 0
    gst_rate: float | None = None
    match: ThreeWayMatchResult
    match_mode: str = "two_way_dn_invoice"
    route_target: str | None = None
    evaluation_status: str | None = None
    document_type_code: str | None = None


class SalesWorkspaceKpis(BaseModel):
    awaiting_so_count: int = 0
    needs_action_count: int = 0
