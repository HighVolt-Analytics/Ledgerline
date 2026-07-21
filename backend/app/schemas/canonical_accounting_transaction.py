"""Provider-neutral canonical accounting transaction for export adapters."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PAYLOAD_VERSION = 1
TRANSACTION_TYPE_SUPPLIER = "SUPPLIER_INVOICE"


def _money(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CanonicalSupplier(BaseModel):
    qll_supplier_id: str | None = None
    legal_name: str
    tax_id: str | None = None
    email: str | None = None
    external_xero_contact_id: str | None = None


class CanonicalTracking(BaseModel):
    category_name: str | None = None
    option_name: str | None = None
    mapped_xero_tracking_category_id: str | None = None
    mapped_xero_tracking_option_id: str | None = None


class CanonicalLine(BaseModel):
    line_id: str
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0.00")
    line_amount: Decimal = Decimal("0.00")
    qll_gl_account_code: str | None = None
    mapped_xero_account_code: str | None = None
    qll_tax_code: str | None = None
    mapped_xero_tax_type: str | None = None
    tracking: list[CanonicalTracking] = Field(default_factory=list)

    @field_validator("quantity", "unit_price", "line_amount", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Any:
        if value is None or value == "":
            return Decimal("0")
        return value


class CanonicalAttachment(BaseModel):
    filename: str
    storage_locator: str
    mime_type: str = "application/pdf"
    size_bytes: int | None = None


class CanonicalAccountingTransaction(BaseModel):
    qll_transaction_id: str
    tenant_id: str
    source_invoice_id: int
    source_document_id: str | None = None
    transaction_type: Literal["SUPPLIER_INVOICE"] = TRANSACTION_TYPE_SUPPLIER
    posting_date: date | None = None
    due_date: date | None = None
    currency: str
    supplier: CanonicalSupplier
    reference: str | None = None
    lines: list[CanonicalLine]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    attachment: CanonicalAttachment | None = None
    idempotency_key: str
    payload_version: int = PAYLOAD_VERSION
    payload_hash: str = ""

    @model_validator(mode="after")
    def _ensure_hash(self) -> CanonicalAccountingTransaction:
        if not self.payload_hash:
            object.__setattr__(self, "payload_hash", compute_payload_hash(self))
        return self

    def model_dump_serialisable(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())


def compute_payload_hash(txn: CanonicalAccountingTransaction | dict[str, Any]) -> str:
    if isinstance(txn, CanonicalAccountingTransaction):
        data = txn.model_dump(mode="json", exclude={"payload_hash"})
    else:
        data = {k: v for k, v in txn.items() if k != "payload_hash"}
    canonical = json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_idempotency_key(
    *,
    tenant_id: uuid.UUID | str,
    source_invoice_id: int,
    payload_version: int,
    payload_hash: str,
) -> str:
    raw = f"{tenant_id}:xero:{source_invoice_id}:v{payload_version}:{payload_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def new_qll_transaction_id(
    *,
    tenant_id: uuid.UUID | str | None = None,
    source_invoice_id: int | None = None,
) -> str:
    if tenant_id is not None and source_invoice_id is not None:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"qll:{tenant_id}:supplier-invoice:{source_invoice_id}",
            )
        )
    return str(uuid.uuid4())


def validate_canonical_totals(
    txn: CanonicalAccountingTransaction,
    *,
    tolerance: Decimal = Decimal("0.02"),
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    line_sum = sum((_money(line.line_amount) for line in txn.lines), Decimal("0.00"))
    expected_total = _money(txn.subtotal) + _money(txn.tax_total)
    if abs(line_sum - _money(txn.subtotal)) > tolerance and txn.lines:
        # Allow tax-inclusive line amounts: compare to total instead
        if abs(line_sum - _money(txn.total)) > tolerance:
            errors.append(
                {
                    "field": "lines",
                    "code": "totals_do_not_reconcile",
                    "message": (
                        f"Line amounts ({line_sum}) do not reconcile to "
                        f"subtotal ({txn.subtotal}) or total ({txn.total})"
                    ),
                }
            )
    if abs(expected_total - _money(txn.total)) > tolerance:
        errors.append(
            {
                "field": "total",
                "code": "totals_do_not_reconcile",
                "message": (
                    f"subtotal ({txn.subtotal}) + tax ({txn.tax_total}) "
                    f"!= total ({txn.total})"
                ),
            }
        )
    return errors
