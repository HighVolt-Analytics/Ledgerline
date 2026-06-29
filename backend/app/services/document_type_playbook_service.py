"""Apply document-type catalogue fields (extraction, bundle, matching) at runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_catalog import get_document_type_definition
from app.services.document_type_field_checks import field_is_present
from app.services.document_type_rule_engine import build_document_classifier_context
from app.services.invoice_data import InvoiceData
from app.services.po_reference import is_plausible_po_reference

_DT_CODE = re.compile(r"^DT-\d{2}$", re.I)

_EXTRACTION_FIELD_HINTS: tuple[tuple[str, str], ...] = (
    ("invoice number", "invoice_no"),
    ("invoice no", "invoice_no"),
    ("invoice date", "invoice_date"),
    ("due date", "due_date"),
    ("po number", "po_reference"),
    ("purchase order", "po_reference"),
    ("vendor", "vendor"),
    ("abn", "abn"),
    ("tax id", "abn"),
    ("line item", "line_items"),
    ("subtotal", "subtotal"),
    ("total", "total"),
    ("gst", "gst"),
    ("bank", "bank_details"),
    ("payment terms", "due_date"),
)

_TERMINAL_SKIP_STATUSES = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


@dataclass(frozen=True)
class PlaybookGateResult:
    missing_bundle_mandatory: tuple[str, ...]
    missing_bundle_conditional_dt: tuple[str, ...]
    conditional_advisories: tuple[str, ...]
    missing_extraction_fields: tuple[str, ...]

    @property
    def blocks_posting(self) -> bool:
        return bool(self.missing_bundle_mandatory or self.missing_extraction_fields)

    def audit_detail(self) -> dict[str, object]:
        return {
            "missing_bundle_mandatory": list(self.missing_bundle_mandatory),
            "missing_bundle_conditional_dt": list(self.missing_bundle_conditional_dt),
            "conditional_advisories": list(self.conditional_advisories),
            "missing_extraction_fields": list(self.missing_extraction_fields),
            "blocks_posting": self.blocks_posting,
        }


def is_dt_code(value: str) -> bool:
    return bool(_DT_CODE.match((value or "").strip()))


def split_bundle_items(items: list[str]) -> tuple[list[str], list[str]]:
    """Return (dt_codes, free_text_advisories)."""
    dt_codes: list[str] = []
    advisories: list[str] = []
    for raw in items:
        token = raw.strip()
        if not token:
            continue
        if is_dt_code(token):
            dt_codes.append(token.upper())
        else:
            advisories.append(token)
    return dt_codes, advisories


def extraction_field_keys_from_playbook(definition: DocumentTypeDefinition) -> list[str]:
    """Legacy: infer keys from human-readable extraction bullet lines."""
    keys: list[str] = []
    seen: set[str] = set()
    for line in definition.extraction:
        lowered = line.strip().lower()
        if not lowered:
            continue
        for hint, key in _EXTRACTION_FIELD_HINTS:
            if hint in lowered and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def effective_extraction_fields(definition: DocumentTypeDefinition) -> list[str]:
    """User-defined extraction keys for drawer display and playbook completeness."""
    return list(definition.extraction_fields or [])


def extraction_fields_for_invoice_code(
    code: str,
    document_types: list[DocumentTypeDefinition] | None,
    *,
    tenant_id: int | None = None,
) -> list[str]:
    definition = get_document_type_definition(
        code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    if definition is None:
        return []
    return effective_extraction_fields(definition)


def effective_document_type_code(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition] | None,
    *,
    tenant_id: int | None = None,
) -> str:
    """Stored DT code, or catalogue match from purchase document role when classifiers missed."""
    stored = (invoice.document_type_code or "").strip().upper()
    if stored:
        return stored
    if not document_types:
        return ""
    from app.services.document_type_catalog import resolve_document_type_for_purchase_kind
    from app.services.purchase_document_service import (
        infer_purchase_document_type,
        normalize_purchase_document_type,
    )

    kind = normalize_purchase_document_type(invoice.purchase_document_type)
    if not kind:
        kind = infer_purchase_document_type(invoice)
    if not kind:
        return ""
    definition = resolve_document_type_for_purchase_kind(kind, document_types)
    if definition is None:
        return ""
    return definition.code.strip().upper()


def effective_required_fields(definition: DocumentTypeDefinition) -> list[str]:
    # Backward-compatible alias: runtime required evidence now follows extraction fields.
    return effective_extraction_fields(definition)


def effective_absent_fields(definition: DocumentTypeDefinition) -> list[str]:
    return list(definition.absent_fields or [])


def missing_extraction_fields(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> list[str]:
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    missing: list[str] = []
    for key in effective_extraction_fields(definition):
        if not field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            missing.append(key)
    return missing


async def _invoice_dt_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
    dt_code: str,
    exclude_invoice_id: int | None,
) -> bool:
    stmt = (
        select(Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.po_reference == po_reference,
            Invoice.document_type_code == dt_code,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _purchase_po_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
) -> bool:
    stmt = (
        select(PurchaseOrder.id)
        .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.po_number == po_reference)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _purchase_grn_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
) -> bool:
    stmt = (
        select(GoodsReceipt.id)
        .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
        .where(
            GoodsReceipt.tenant_id == tenant_id,
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.po_number == po_reference,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _purchase_document_upload_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
    purchase_document_type: str,
) -> bool:
    inv = await session.execute(
        select(Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.po_reference == po_reference,
            Invoice.purchase_document_type == purchase_document_type,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    return inv.scalar_one_or_none() is not None


async def _bundle_dt_satisfied(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
    dt_code: str,
    exclude_invoice_id: int | None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> bool:
    code = dt_code.strip().upper()
    member = get_document_type_definition(code, document_types=document_types, tenant_id=tenant_id)
    role = (member.purchase_bundle_role if member else "") or ""

    if role == "po":
        if await _purchase_po_present(session, tenant_id=tenant_id, po_reference=po_reference):
            return True
        if await _purchase_document_upload_present(
            session, tenant_id=tenant_id, po_reference=po_reference, purchase_document_type="po"
        ):
            return True
    elif role == "grn":
        if await _purchase_grn_present(session, tenant_id=tenant_id, po_reference=po_reference):
            return True
        if await _purchase_document_upload_present(
            session, tenant_id=tenant_id, po_reference=po_reference, purchase_document_type="grn"
        ):
            return True

    return await _invoice_dt_present(
        session,
        tenant_id=tenant_id,
        po_reference=po_reference,
        dt_code=code,
        exclude_invoice_id=exclude_invoice_id,
    )


async def missing_bundle_dt_codes(
    session: AsyncSession,
    *,
    invoice: Invoice,
    dt_codes: list[str],
    document_types: list[DocumentTypeDefinition] | None = None,
) -> list[str]:
    po_reference = (invoice.po_reference or "").strip()
    if not po_reference or not is_plausible_po_reference(po_reference):
        return list(dt_codes)
    missing: list[str] = []
    for code in dt_codes:
        if not await _bundle_dt_satisfied(
            session,
            tenant_id=invoice.tenant_id,
            po_reference=po_reference,
            dt_code=code,
            exclude_invoice_id=invoice.id,
            document_types=document_types,
        ):
            missing.append(code)
    return missing


async def evaluate_playbook_gates(
    session: AsyncSession,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    definition: DocumentTypeDefinition | None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> PlaybookGateResult:
    if definition is None:
        return PlaybookGateResult(
            missing_bundle_mandatory=(),
            missing_bundle_conditional_dt=(),
            conditional_advisories=(),
            missing_extraction_fields=(),
        )

    mandatory_dt, _ = split_bundle_items(definition.bundle_mandatory)
    conditional_dt, conditional_advisories = split_bundle_items(definition.bundle_conditional)

    missing_mandatory = await missing_bundle_dt_codes(
        session,
        invoice=invoice,
        dt_codes=mandatory_dt,
        document_types=document_types,
    )
    missing_conditional = await missing_bundle_dt_codes(
        session,
        invoice=invoice,
        dt_codes=conditional_dt,
        document_types=document_types,
    )

    return PlaybookGateResult(
        missing_bundle_mandatory=tuple(missing_mandatory),
        missing_bundle_conditional_dt=tuple(missing_conditional),
        conditional_advisories=tuple(conditional_advisories),
        missing_extraction_fields=tuple(
            missing_extraction_fields(definition, invoice=invoice, parsed=parsed)
        ),
    )


def resolve_definition_for_invoice(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition] | None,
) -> DocumentTypeDefinition | None:
    code = (invoice.document_type_code or "").strip().upper()
    if not code:
        return None
    return get_document_type_definition(code, document_types=document_types, tenant_id=invoice.tenant_id)


def playbook_validation_results(playbook: PlaybookGateResult | None) -> list[object]:
    """Catalogue-driven validation rows (VR-PB*) for audit trail."""
    from app.services.validator import ValidationResult

    if playbook is None:
        return []

    results: list[ValidationResult] = []
    if playbook.missing_bundle_mandatory:
        codes = ", ".join(playbook.missing_bundle_mandatory)
        results.append(
            ValidationResult(
                "VR-PB02",
                False,
                f"Mandatory bundle members missing for PO: {codes}",
            )
        )
    if playbook.missing_bundle_conditional_dt:
        codes = ", ".join(playbook.missing_bundle_conditional_dt)
        results.append(
            ValidationResult(
                "VR-PB04",
                True,
                f"Conditional bundle members not yet present: {codes}",
            )
        )
    if playbook.conditional_advisories:
        notes = "; ".join(playbook.conditional_advisories[:3])
        results.append(
            ValidationResult(
                "VR-PB04",
                True,
                f"Conditional bundle advisories: {notes}",
            )
        )
    if playbook.missing_extraction_fields:
        fields = ", ".join(playbook.missing_extraction_fields)
        results.append(
            ValidationResult(
                "VR-PB01",
                True,
                f"Playbook extraction fields not yet captured: {fields}",
            )
        )
    return results
