"""Apply document-type catalogue fields (extraction, bundle, matching) at runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_note import DeliveryNote
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import ROUTE_SALES, get_document_type_definition
from app.services.classification.document_type_field_checks import field_is_present
from app.services.classification.document_type_rule_engine import build_document_classifier_context
from app.services.invoice.invoice_data import InvoiceData
from app.services.purchase.po_reference import is_plausible_po_reference
from app.services.sales.so_reference import is_plausible_so_reference, resolve_so_reference_from_invoice

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
    missing_optional_extraction_fields: tuple[str, ...] = ()
    linkage_key: str | None = None
    linkage_key_missing: bool = False
    linkage_book: str | None = None  # "purchase" | "sales"
    block_reason: str | None = None
    missing_bundle_mandatory_labels: dict[str, str] | None = None

    @property
    def blocks_posting(self) -> bool:
        return bool(self.missing_bundle_mandatory or self.missing_extraction_fields)

    def audit_detail(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "missing_bundle_mandatory": list(self.missing_bundle_mandatory),
            "missing_bundle_conditional_dt": list(self.missing_bundle_conditional_dt),
            "conditional_advisories": list(self.conditional_advisories),
            "missing_extraction_fields": list(self.missing_extraction_fields),
            "missing_optional_extraction_fields": list(self.missing_optional_extraction_fields),
            "blocks_posting": self.blocks_posting,
            "linkage_key": self.linkage_key,
            "linkage_key_missing": self.linkage_key_missing,
            "linkage_book": self.linkage_book,
            "block_reason": self.block_reason,
        }
        if self.missing_bundle_mandatory_labels:
            payload["missing_bundle_mandatory_labels"] = self.missing_bundle_mandatory_labels
        return payload


def _dt_display_labels(
    codes: list[str],
    document_types: list[DocumentTypeDefinition] | None,
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for raw in codes:
        token = raw.strip().upper()
        if not token:
            continue
        defn = get_document_type_definition(token, document_types=document_types)
        if defn is not None:
            labels[token] = (defn.short_title or defn.title or token).strip() or token
        else:
            labels[token] = token
    return labels


def _resolve_playbook_block_reason(
    *,
    enforce_bundle: bool,
    mandatory_dt: list[str],
    linkage_plausible: bool,
    missing_mandatory: list[str],
    missing_extraction: list[str],
) -> str | None:
    if not missing_mandatory and not missing_extraction:
        return None
    linkage_missing = enforce_bundle and bool(mandatory_dt) and not linkage_plausible
    if linkage_missing:
        return "linkage"
    if missing_mandatory:
        return "bundle"
    if missing_extraction:
        return "extraction"
    return None


def _linkage_context(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
) -> tuple[str, str | None, bool, str]:
    """Return (raw_reference, normalized_key, plausible, book) for dossier linkage."""
    invoice_no = (invoice.invoice_no or "").strip()
    route = (invoice.route_target or (definition.route_target if definition else None) or "").strip()
    if route == ROUTE_SALES:
        raw = (resolve_so_reference_from_invoice(invoice) or "").strip()
        key = raw if is_plausible_so_reference(raw) else None
        if key is not None:
            return raw, key, True, "sales"
        if invoice_no:
            return invoice_no, invoice_no, True, "invoice_no"
        return raw, None, False, "sales"
    raw = (invoice.po_reference or "").strip()
    key = raw if is_plausible_po_reference(raw) else None
    if key is not None:
        return raw, key, True, "purchase"
    if invoice_no:
        return invoice_no, invoice_no, True, "invoice_no"
    return raw, None, False, "purchase"


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
    from app.services.classification.document_type_catalog import resolve_document_type_for_purchase_kind
    from app.services.purchase.purchase_document_service import (
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
    """Compulsory field keys — subset of extraction_fields."""
    explicit = list(definition.required_fields or [])
    if explicit:
        return explicit
    return list(definition.extraction_fields or [])


def effective_playbook_required_fields(definition: DocumentTypeDefinition) -> list[str]:
    """Compulsory keys that may block playbook (excludes ingest/OCR infrastructure)."""
    from app.services.classification.document_type_field_keys import (
        CANONICAL_EXTRACTION_FIELD_KEYS,
        playbook_blockable_field_keys,
    )
    from app.services.classification.document_type_playbook_profile_service import effective_playbook_profile

    keys = playbook_blockable_field_keys(effective_required_fields(definition))
    if effective_playbook_profile(definition) != "supporting":
        return keys

    # Supporting / vault docs: block on business identifiers only, not optional customs.
    hard = {
        key
        for key in keys
        if key in {"vendor", "permit_no", "po_reference"}
        or (
            key in CANONICAL_EXTRACTION_FIELD_KEYS
            and key not in {"attachment_name", "document_text", "document_heading"}
        )
    }
    return sorted(hard) if hard else keys


def effective_optional_extraction_fields(definition: DocumentTypeDefinition) -> list[str]:
    """Extraction keys that are not compulsory."""
    compulsory = set(effective_required_fields(definition))
    return [key for key in effective_extraction_fields(definition) if key not in compulsory]


def effective_absent_fields(definition: DocumentTypeDefinition) -> list[str]:
    return list(definition.absent_fields or [])


def confidence_gate_fields(definition: DocumentTypeDefinition | None) -> list[str]:
    """Per-DT fields monitored by the post-extract LLM confidence gate."""
    if definition is None:
        return ["vendor", "total"]
    required = set(effective_playbook_required_fields(definition))
    absent = {str(f).strip().lower() for f in (definition.absent_fields or []) if str(f).strip()}
    return sorted(required - absent)


def missing_extraction_fields(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> list[str]:
    """Missing compulsory (required) fields."""
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    missing: list[str] = []
    for key in effective_playbook_required_fields(definition):
        if not field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            missing.append(key)
    return missing


def missing_optional_extraction_fields(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> list[str]:
    """Missing optional extraction targets (warn-only via VR-PB01)."""
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    missing: list[str] = []
    for key in effective_optional_extraction_fields(definition):
        if not field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            missing.append(key)
    return missing


def _normalize_po_ref_token(po_reference: str) -> str:
    return (po_reference or "").strip().upper()


def _invoice_po_ref_equals(po_reference: str):
    token = _normalize_po_ref_token(po_reference)
    return func.upper(func.coalesce(Invoice.po_reference, "")) == token


def _purchase_order_po_ref_equals(po_reference: str):
    token = _normalize_po_ref_token(po_reference)
    return func.upper(func.coalesce(PurchaseOrder.po_number, "")) == token


def _dt_codes_for_bundle_role(
    document_types: list[DocumentTypeDefinition] | None,
    role: str,
    *,
    bundle_field: str = "purchase",
) -> list[str]:
    token = (role or "").strip().lower()
    if not token or not document_types:
        return []
    codes: list[str] = []
    seen: set[str] = set()
    for row in document_types:
        if not row.enabled:
            continue
        if bundle_field == "sales":
            row_role = (row.sales_bundle_role or "").strip().lower()
        else:
            row_role = (row.purchase_bundle_role or "").strip().lower()
        if row_role != token:
            continue
        code = (row.code or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


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
            _invoice_po_ref_equals(po_reference),
            Invoice.document_type_code == dt_code,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def invoice_dt_present_by_invoice_no(
    session: AsyncSession,
    *,
    tenant_id: int,
    invoice_no: str,
    dt_code: str,
    exclude_invoice_id: int | None = None,
) -> bool:
    """True when another org document shares invoice_no and has the given DT code."""
    token = (invoice_no or "").strip()
    code = (dt_code or "").strip().upper()
    if not token or not code:
        return False
    stmt = (
        select(Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_no == token,
            Invoice.document_type_code == code,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _invoice_any_bundle_role_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
    role: str,
    exclude_invoice_id: int | None,
    document_types: list[DocumentTypeDefinition] | None,
) -> bool:
    """Sibling upload classified to any enabled DT with this purchase bundle role."""
    token = (role or "").strip().lower()
    if token not in {"po", "grn"}:
        return False
    if await _purchase_document_upload_present(
        session,
        tenant_id=tenant_id,
        po_reference=po_reference,
        purchase_document_type=token,
    ):
        return True
    for code in _dt_codes_for_bundle_role(document_types, token):
        if await _invoice_dt_present(
            session,
            tenant_id=tenant_id,
            po_reference=po_reference,
            dt_code=code,
            exclude_invoice_id=exclude_invoice_id,
        ):
            return True
    return False


async def _purchase_po_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
) -> bool:
    stmt = (
        select(PurchaseOrder.id)
        .where(
            PurchaseOrder.tenant_id == tenant_id,
            _purchase_order_po_ref_equals(po_reference),
        )
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
            _purchase_order_po_ref_equals(po_reference),
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
            _invoice_po_ref_equals(po_reference),
            Invoice.purchase_document_type == purchase_document_type,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    return inv.scalar_one_or_none() is not None


def _normalize_so_ref_token(so_reference: str) -> str:
    return (so_reference or "").strip().upper()


def _invoice_so_ref_equals(so_reference: str):
    token = _normalize_so_ref_token(so_reference)
    return func.upper(func.coalesce(Invoice.so_reference, "")) == token


def _sales_order_so_ref_equals(so_reference: str):
    token = _normalize_so_ref_token(so_reference)
    return func.upper(func.coalesce(SalesOrder.so_number, "")) == token


async def _invoice_dt_present_on_so(
    session: AsyncSession,
    *,
    tenant_id: int,
    so_reference: str,
    dt_code: str,
    exclude_invoice_id: int | None,
) -> bool:
    stmt = (
        select(Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            _invoice_so_ref_equals(so_reference),
            Invoice.document_type_code == dt_code,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _sales_document_upload_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    so_reference: str,
    sales_document_type: str,
) -> bool:
    inv = await session.execute(
        select(Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            _invoice_so_ref_equals(so_reference),
            Invoice.sales_document_type == sales_document_type,
            Invoice.status.not_in(_TERMINAL_SKIP_STATUSES),
        )
        .limit(1)
    )
    return inv.scalar_one_or_none() is not None


async def _invoice_any_sales_bundle_role_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    so_reference: str,
    role: str,
    exclude_invoice_id: int | None,
    document_types: list[DocumentTypeDefinition] | None,
) -> bool:
    token = (role or "").strip().lower()
    if token not in {"so", "dn"}:
        return False
    if await _sales_document_upload_present(
        session,
        tenant_id=tenant_id,
        so_reference=so_reference,
        sales_document_type=token,
    ):
        return True
    for code in _dt_codes_for_bundle_role(document_types, token, bundle_field="sales"):
        if await _invoice_dt_present_on_so(
            session,
            tenant_id=tenant_id,
            so_reference=so_reference,
            dt_code=code,
            exclude_invoice_id=exclude_invoice_id,
        ):
            return True
    return False


async def _sales_so_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    so_reference: str,
) -> bool:
    stmt = (
        select(SalesOrder.id)
        .where(
            SalesOrder.tenant_id == tenant_id,
            _sales_order_so_ref_equals(so_reference),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _sales_dn_present(
    session: AsyncSession,
    *,
    tenant_id: int,
    so_reference: str,
) -> bool:
    stmt = (
        select(DeliveryNote.id)
        .join(SalesOrder, DeliveryNote.sales_order_id == SalesOrder.id)
        .where(
            DeliveryNote.tenant_id == tenant_id,
            SalesOrder.tenant_id == tenant_id,
            _sales_order_so_ref_equals(so_reference),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def _infer_sales_bundle_role(definition: DocumentTypeDefinition | None) -> str:
    if definition is None:
        return ""
    explicit = (definition.sales_bundle_role or "").strip().lower()
    if explicit in {"so", "dn"}:
        return explicit
    label = f"{definition.short_title or ''} {definition.title or ''}".lower()
    if any(token in label for token in ("delivery note", "dispatch", "dn ")):
        return "dn"
    if any(token in label for token in ("sales order", "so ", "so-")):
        return "so"
    return ""


async def _sales_bundle_dt_satisfied(
    session: AsyncSession,
    *,
    tenant_id: int,
    so_reference: str,
    dt_code: str,
    exclude_invoice_id: int | None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> bool:
    code = dt_code.strip().upper()
    member = get_document_type_definition(code, document_types=document_types, tenant_id=tenant_id)
    role = _infer_sales_bundle_role(member)

    if role == "so":
        if await _sales_so_present(session, tenant_id=tenant_id, so_reference=so_reference):
            return True
        if await _invoice_any_sales_bundle_role_present(
            session,
            tenant_id=tenant_id,
            so_reference=so_reference,
            role="so",
            exclude_invoice_id=exclude_invoice_id,
            document_types=document_types,
        ):
            return True
    elif role == "dn":
        if await _sales_dn_present(session, tenant_id=tenant_id, so_reference=so_reference):
            return True
        if await _invoice_any_sales_bundle_role_present(
            session,
            tenant_id=tenant_id,
            so_reference=so_reference,
            role="dn",
            exclude_invoice_id=exclude_invoice_id,
            document_types=document_types,
        ):
            return True

    if await _invoice_dt_present_on_so(
        session,
        tenant_id=tenant_id,
        so_reference=so_reference,
        dt_code=code,
        exclude_invoice_id=exclude_invoice_id,
    ):
        return True

    return False


def _infer_purchase_bundle_role(definition: DocumentTypeDefinition | None) -> str:
    if definition is None:
        return ""
    explicit = (definition.purchase_bundle_role or "").strip().lower()
    if explicit in {"po", "grn"}:
        return explicit
    label = f"{definition.short_title or ''} {definition.title or ''}".lower()
    if any(token in label for token in ("grn", "goods receipt", "delivery", "receipt note")):
        return "grn"
    if any(token in label for token in ("purchase order", "po (", "po copy", " po")):
        return "po"
    return ""


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
    role = _infer_purchase_bundle_role(member)

    if role == "po":
        if await _purchase_po_present(session, tenant_id=tenant_id, po_reference=po_reference):
            return True
        if await _invoice_any_bundle_role_present(
            session,
            tenant_id=tenant_id,
            po_reference=po_reference,
            role="po",
            exclude_invoice_id=exclude_invoice_id,
            document_types=document_types,
        ):
            return True
    elif role == "grn":
        if await _purchase_grn_present(session, tenant_id=tenant_id, po_reference=po_reference):
            return True
        if await _invoice_any_bundle_role_present(
            session,
            tenant_id=tenant_id,
            po_reference=po_reference,
            role="grn",
            exclude_invoice_id=exclude_invoice_id,
            document_types=document_types,
        ):
            return True

    if await _invoice_dt_present(
        session,
        tenant_id=tenant_id,
        po_reference=po_reference,
        dt_code=code,
        exclude_invoice_id=exclude_invoice_id,
    ):
        return True

    return False


async def missing_bundle_dt_codes(
    session: AsyncSession,
    *,
    invoice: Invoice,
    dt_codes: list[str],
    document_types: list[DocumentTypeDefinition] | None = None,
) -> list[str]:
    invoice_no = (invoice.invoice_no or "").strip()
    route = (invoice.route_target or "").strip()

    if route == ROUTE_SALES:
        so_reference = (resolve_so_reference_from_invoice(invoice) or "").strip()
        if so_reference and is_plausible_so_reference(so_reference):
            missing: list[str] = []
            for code in dt_codes:
                satisfied = await _sales_bundle_dt_satisfied(
                    session,
                    tenant_id=invoice.tenant_id,
                    so_reference=so_reference,
                    dt_code=code,
                    exclude_invoice_id=invoice.id,
                    document_types=document_types,
                )
                if not satisfied and invoice_no:
                    satisfied = await invoice_dt_present_by_invoice_no(
                        session,
                        tenant_id=invoice.tenant_id,
                        invoice_no=invoice_no,
                        dt_code=code,
                        exclude_invoice_id=invoice.id,
                    )
                if not satisfied:
                    missing.append(code)
            return missing
        if invoice_no:
            missing = []
            for code in dt_codes:
                if not await invoice_dt_present_by_invoice_no(
                    session,
                    tenant_id=invoice.tenant_id,
                    invoice_no=invoice_no,
                    dt_code=code,
                    exclude_invoice_id=invoice.id,
                ):
                    missing.append(code)
            return missing
        return list(dt_codes)

    po_reference = (invoice.po_reference or "").strip()
    if po_reference and is_plausible_po_reference(po_reference):
        missing = []
        for code in dt_codes:
            satisfied = await _bundle_dt_satisfied(
                session,
                tenant_id=invoice.tenant_id,
                po_reference=po_reference,
                dt_code=code,
                exclude_invoice_id=invoice.id,
                document_types=document_types,
            )
            if not satisfied and invoice_no:
                satisfied = await invoice_dt_present_by_invoice_no(
                    session,
                    tenant_id=invoice.tenant_id,
                    invoice_no=invoice_no,
                    dt_code=code,
                    exclude_invoice_id=invoice.id,
                )
            if not satisfied:
                missing.append(code)
        return missing

    if invoice_no:
        missing = []
        for code in dt_codes:
            if not await invoice_dt_present_by_invoice_no(
                session,
                tenant_id=invoice.tenant_id,
                invoice_no=invoice_no,
                dt_code=code,
                exclude_invoice_id=invoice.id,
            ):
                missing.append(code)
        return missing

    return list(dt_codes)


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

    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
        should_enforce_bundle_mandatory,
    )

    mandatory_dt, _ = split_bundle_items(definition.bundle_mandatory)
    conditional_dt, conditional_advisories = split_bundle_items(definition.bundle_conditional)

    missing_mandatory = await missing_bundle_dt_codes(
        session,
        invoice=invoice,
        dt_codes=mandatory_dt,
        document_types=document_types,
    )

    profile = effective_playbook_profile(definition)
    if profile in {"ar_goods", "ar_goods_2way"} and missing_mandatory:
        relaxed: list[str] = []
        for code in missing_mandatory:
            member = get_document_type_definition(code, document_types=document_types)
            if _infer_sales_bundle_role(member) == "so":
                continue
            relaxed.append(code)
        missing_mandatory = relaxed

    missing_conditional = await missing_bundle_dt_codes(
        session,
        invoice=invoice,
        dt_codes=conditional_dt,
        document_types=document_types,
    )
    missing_extract = missing_extraction_fields(definition, invoice=invoice, parsed=parsed)
    missing_optional = missing_optional_extraction_fields(
        definition,
        invoice=invoice,
        parsed=parsed,
    )

    po_reference = (invoice.po_reference or "").strip()
    enforce_bundle = should_enforce_bundle_mandatory(definition)
    _, linkage_key, linkage_plausible, linkage_book = _linkage_context(invoice, definition)
    if profile in {"ar_goods", "ar_goods_2way"} and (invoice.invoice_no or "").strip():
        linkage_plausible = True
        linkage_book = linkage_book or "invoice_no"
    linkage_key_missing = bool(
        enforce_bundle
        and mandatory_dt
        and not linkage_plausible
    )
    block_reason = _resolve_playbook_block_reason(
        enforce_bundle=enforce_bundle,
        mandatory_dt=mandatory_dt,
        linkage_plausible=linkage_plausible,
        missing_mandatory=missing_mandatory,
        missing_extraction=missing_extract,
    )

    result = PlaybookGateResult(
        missing_bundle_mandatory=tuple(missing_mandatory),
        missing_bundle_conditional_dt=tuple(missing_conditional),
        conditional_advisories=tuple(conditional_advisories),
        missing_extraction_fields=tuple(missing_extract),
        missing_optional_extraction_fields=tuple(missing_optional),
        linkage_key=linkage_key,
        linkage_key_missing=linkage_key_missing,
        linkage_book=linkage_book,
        block_reason=block_reason,
        missing_bundle_mandatory_labels=_dt_display_labels(missing_mandatory, document_types)
        or None,
    )
    return result


def resolve_definition_for_invoice(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition] | None,
) -> DocumentTypeDefinition | None:
    code = (invoice.document_type_code or "").strip().upper()
    if not code:
        return None
    return get_document_type_definition(code, document_types=document_types, tenant_id=invoice.tenant_id)


def resolve_playbook_exception(detail: dict[str, object]) -> tuple[str, str, str]:
    """Return (exception_code, failure_reason, remediation) from playbook audit detail."""
    playbook = detail.get("playbook") if isinstance(detail.get("playbook"), dict) else detail
    if not isinstance(playbook, dict):
        playbook = detail

    block_reason = str(playbook.get("block_reason") or "").strip().lower()
    missing = playbook.get("missing_bundle_mandatory") or []
    if not isinstance(missing, list):
        missing = []
    labels = playbook.get("missing_bundle_mandatory_labels")
    if not isinstance(labels, dict):
        labels = {}

    missing_extract = playbook.get("missing_extraction_fields") or []
    if not isinstance(missing_extract, list):
        missing_extract = []

    if block_reason == "linkage" or playbook.get("linkage_key_missing"):
        book = str(playbook.get("linkage_book") or "").strip().lower()
        if book == "sales":
            return (
                "LINKAGE_KEY_MISSING",
                "SO reference required to link the sales order dossier",
                "Extract or enter a valid SO reference on this invoice, then upload supporting documents (SO copy and DN) on the same SO.",
            )
        return (
            "LINKAGE_KEY_MISSING",
            "PO reference required to link the purchase order dossier",
            "Extract or enter a valid PO reference on this invoice, then upload supporting documents (PO copy and GRN) on the same PO.",
        )

    if block_reason == "extraction" or (missing_extract and not missing):
        fields = ", ".join(str(f) for f in missing_extract)
        return (
            "EXTRACTION_INCOMPLETE",
            f"Required fields missing: {fields}" if fields else "Required extraction fields missing",
            "Correct extracted fields or reprocess after capture quality improves.",
        )

    if missing:
        parts: list[str] = []
        for code in missing:
            token = str(code).strip().upper()
            label = str(labels.get(token) or labels.get(str(code)) or token)
            parts.append(f"{label} ({token})" if label != token else token)
        joined = ", ".join(parts)
        return (
            "BUNDLE_INCOMPLETE",
            f"Required supporting documents missing: {joined}",
            _REMEDIATION_BUNDLE,
        )

    return (
        "BUNDLE_INCOMPLETE",
        "Supporting document requirements block posting",
        _REMEDIATION_BUNDLE,
    )


_REMEDIATION_BUNDLE = (
    "Upload the missing required supporting documents on the same PO or SO reference."
)


def suggest_reclassify_direct_expense_code(
    playbook: PlaybookGateResult,
    definition: DocumentTypeDefinition | None,
    document_types: list[DocumentTypeDefinition] | None,
) -> str | None:
    """Finance-safe hint when a PO profile invoice has no linkage key."""
    if definition is None or not document_types:
        return None
    if not playbook.linkage_key_missing:
        return None
    from app.services.classification.document_type_playbook_profile_service import effective_playbook_profile

    profile = effective_playbook_profile(definition)
    if profile not in {"po_goods", "po_services", "import_dossier"}:
        return None
    for row in document_types:
        if not row.enabled:
            continue
        if effective_playbook_profile(row) == "direct_expense":
            code = (row.code or "").strip().upper()
            if code:
                return code
    return None


def playbook_validation_results(playbook: PlaybookGateResult | None) -> list[object]:
    """Catalogue-driven validation rows (VR-PB*) for audit trail."""
    from app.services.rule_book.validator import ValidationResult

    if playbook is None:
        return []

    results: list[ValidationResult] = []
    if playbook.missing_bundle_mandatory:
        codes = ", ".join(playbook.missing_bundle_mandatory)
        book = (playbook.linkage_book or "purchase").strip().lower()
        ref_label = "SO" if book == "sales" else "PO"
        results.append(
            ValidationResult(
                "VR-PB02",
                False,
                f"Required supporting documents missing for {ref_label}: {codes}",
            )
        )
    if playbook.missing_bundle_conditional_dt:
        codes = ", ".join(playbook.missing_bundle_conditional_dt)
        results.append(
            ValidationResult(
                "VR-PB04",
                True,
                f"Recommended supporting documents not yet present: {codes}",
            )
        )
    if playbook.conditional_advisories:
        notes = "; ".join(playbook.conditional_advisories[:3])
        results.append(
            ValidationResult(
                "VR-PB04",
                True,
                f"Recommended supporting document advisories: {notes}",
            )
        )
    if playbook.missing_optional_extraction_fields:
        fields = ", ".join(playbook.missing_optional_extraction_fields)
        results.append(
            ValidationResult(
                "VR-PB01",
                True,
                f"Optional extraction fields not yet captured: {fields}",
            )
        )
    return results
