"""Purchase order and three-way match schemas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.dossier import DossierMatchSummaryResponse


class MatchAmountLine(BaseModel):
    """Quantity / unit price / line value for one leg of the match."""

    qty: float
    uom: str | None = None
    unit_price: float | None = None
    line_value: float | None = None


class ThreeWayMatchDisplay(BaseModel):
    """Human-readable document amounts for each leg of the match."""

    base_uom: str | None = None
    po_on_document: MatchAmountLine
    po_for_match: MatchAmountLine
    grn_on_document: MatchAmountLine | None = None
    grn_for_match: MatchAmountLine | None = None
    invoice_on_document: MatchAmountLine | None = None
    invoice_for_match: MatchAmountLine | None = None
    match_explanation: str | None = None


class ThreeWayMatchResult(BaseModel):
    status: str
    qty_variance_value: float
    price_variance_value: float
    total_deviation: float
    po_value: float
    invoice_value: float
    invoice_gst: float
    invoice_total: float
    display: ThreeWayMatchDisplay | None = None


class PurchaseOrderResponse(BaseModel):
    id: int
    po_number: str
    vendor: str | None = None
    po_date: date | None = None
    item: str | None = None
    requestor: str | None = None
    po_qty: float
    po_unit_price: float
    grn_qty: float | None = None
    grn_date: date | None = None
    grn_receiver: str | None = None
    grn_condition: str | None = None
    invoice_id: int | None = None
    po_document_id: int | None = None
    grn_document_id: int | None = None
    invoice_no: str | None = None
    invoice_qty: float = 0
    invoice_unit_price: float = 0
    gst_rate: float = 0.1
    variance_approved: bool = False
    status: str
    three_way_match_status: str | None = None
    match: ThreeWayMatchResult
    match_mode: str = "three_way_po_grn"
    route_target: str | None = None
    evaluation_status: str | None = None
    matched_rule_ids: list[str] = Field(default_factory=list)
    matched_rule_name: str | None = None
    matched_gl: str | None = None
    ledger: str | None = None
    sub_ledger: str | None = None
    purchase_rule_id: str | None = None


class GoodsReceiptCreate(BaseModel):
    grn_qty: Decimal = Field(gt=0)
    grn_date: date | None = None
    receiver: str | None = None
    condition_note: str | None = None


class PurchaseDossierMember(BaseModel):
    role: str
    label: str
    invoice_id: int | None = None
    document_ref: str | None = None
    present: bool = False
    has_stored_file: bool = False
    is_current: bool = False


class PurchaseDossierResponse(BaseModel):
    po_reference: str | None = None
    current_role: str | None = None
    members: list[PurchaseDossierMember] = Field(default_factory=list)
    purchase_order_id: int | None = None
    match: ThreeWayMatchResult | None = None
    match_status: str | None = None
    match_summary: DossierMatchSummaryResponse | None = None
    purchase_register: PurchaseOrderResponse | None = None
