"""Mobile/manual capture: stamp DT + user fields and skip OCR extraction."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import (
    get_document_type_definition,
    resolved_route_for_definition,
)
from app.services.classification.document_type_field_keys import (
    INFRASTRUCTURE_EXTRACTION_FIELD_KEYS,
    playbook_blockable_field_keys,
)
from app.services.classification.document_type_playbook_service import (
    effective_extraction_fields,
    effective_required_fields,
)
from app.services.extraction.extraction_field_values import (
    INVOICE_SCALAR_ATTRS,
    merge_invoice_extracted_fields,
)
from app.services.invoice.processing_override_catalog import set_skip_extraction
from app.services.purchase.team_expense_kind_service import document_type_team_expense_kind


class ManualCaptureError(ValueError):
    """User-facing validation error for manual capture."""


def parse_manual_fields_payload(raw: str | None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Parse fields JSON into scalar map + optional line_items rows."""
    if raw is None or not str(raw).strip():
        raise ManualCaptureError("fields JSON is required")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManualCaptureError("fields must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ManualCaptureError("fields must be a JSON object")

    scalars: dict[str, str] = {}
    line_items: list[dict[str, Any]] = []
    for key, value in parsed.items():
        token = str(key or "").strip().lower()
        if not token:
            continue
        if token == "line_items":
            rows = value
            if isinstance(rows, str):
                try:
                    rows = json.loads(rows)
                except json.JSONDecodeError as exc:
                    raise ManualCaptureError("line_items must be a JSON array") from exc
            if not isinstance(rows, list):
                raise ManualCaptureError("line_items must be an array")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                desc = str(row.get("description") or "").strip()
                if not desc:
                    continue
                line_items.append(
                    {
                        "description": desc,
                        "qty": row.get("qty"),
                        "unit_price": row.get("unit_price"),
                        "amount": row.get("amount"),
                        "tax_amount": row.get("tax_amount"),
                    }
                )
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            scalars[token] = text
    return scalars, line_items


# Back-compat alias used by older tests / callers
def parse_manual_fields_json(raw: str | None) -> dict[str, str]:
    scalars, _lines = parse_manual_fields_payload(raw)
    return scalars


def resolve_active_document_type(
    code: str,
    document_types: list[DocumentTypeDefinition] | None,
) -> DocumentTypeDefinition:
    token = (code or "").strip().upper()
    if not token:
        raise ManualCaptureError("document_type_code is required")
    definition = get_document_type_definition(token, document_types=document_types)
    if definition is None:
        raise ManualCaptureError(f"Unknown document type '{token}'")
    if not getattr(definition, "enabled", True):
        raise ManualCaptureError(f"Document type '{token}' is disabled")
    return definition


def form_keys_for_manual_form(definition: DocumentTypeDefinition) -> list[str]:
    """All catalogue extraction keys for the form (required ∪ extraction), minus OCR infrastructure."""
    required = playbook_blockable_field_keys(effective_required_fields(definition))
    extraction = playbook_blockable_field_keys(effective_extraction_fields(definition))
    seen: set[str] = set()
    out: list[str] = []
    for key in required + extraction:
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def required_keys_for_manual_form(definition: DocumentTypeDefinition) -> list[str]:
    """Compulsory keys the user must fill (starred required, else all form keys)."""
    required = playbook_blockable_field_keys(effective_required_fields(definition))
    if required:
        return required
    return form_keys_for_manual_form(definition)


def validate_manual_fields(
    definition: DocumentTypeDefinition,
    fields: dict[str, str],
    *,
    line_items: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Validate compulsory keys; return required key list."""
    form_keys = form_keys_for_manual_form(definition)
    if not form_keys:
        raise ManualCaptureError(
            "This document type has no fillable fields configured"
        )
    required = required_keys_for_manual_form(definition)
    rows = list(line_items or [])
    missing: list[str] = []
    for key in required:
        if key == "line_items":
            if not rows:
                missing.append("line_items")
            continue
        if key == "bank_details":
            bsb = (fields.get("bank_bsb") or "").strip()
            acct = (fields.get("bank_account") or "").strip()
            blob = (fields.get("bank_details") or "").strip()
            if not blob and not (bsb or acct):
                missing.append("bank_details")
            continue
        if not (fields.get(key) or "").strip():
            missing.append(key)
    if missing:
        raise ManualCaptureError(
            "Missing required fields: " + ", ".join(missing)
        )
    return required


def _parse_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_money(value: str) -> Decimal | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def apply_manual_fields_to_invoice(invoice: Invoice, fields: dict[str, str]) -> None:
    """Write user-entered keys onto invoice columns and extracted_fields."""
    extracted_patch: dict[str, str] = {}
    for key, raw in fields.items():
        token = (key or "").strip().lower()
        value = (raw or "").strip()
        if not token or not value:
            continue
        if token in INFRASTRUCTURE_EXTRACTION_FIELD_KEYS:
            continue
        if token in {"subtotal", "gst", "total", "gst_rate"}:
            money = _parse_money(value)
            if money is not None:
                setattr(invoice, token, money)
            extracted_patch[token] = value
            continue
        if token in {"invoice_date", "due_date"}:
            parsed = _parse_date(value)
            if parsed is not None:
                setattr(invoice, token, parsed)
            extracted_patch[token] = value
            continue
        if token == "currency":
            code = value.strip().upper()
            if len(code) == 3 and code.isalpha():
                invoice.currency = code
            extracted_patch[token] = value
            continue
        if token in INVOICE_SCALAR_ATTRS:
            setattr(invoice, token, value)
            extracted_patch[token] = value
            continue
        if token in {"account_code", "account_name", "so_reference", "email_sender"}:
            if token == "account_code":
                invoice.account_code = value
            elif token == "account_name":
                invoice.account_name = value
            elif token == "so_reference":
                invoice.so_reference = value
            elif token == "email_sender":
                invoice.email_sender = value
            extracted_patch[token] = value
            continue
        if token == "bank_details":
            extracted_patch[token] = value
            # Accept "BSB · account" or "BSB / account"
            parts = [p.strip() for p in value.replace("/", "·").split("·") if p.strip()]
            if len(parts) >= 2:
                invoice.bank_bsb = parts[0][:32]
                invoice.bank_account = parts[1][:64]
            continue
        if token == "bank_bsb":
            invoice.bank_bsb = value[:32]
            extracted_patch[token] = value
            continue
        if token == "bank_account":
            invoice.bank_account = value[:64]
            extracted_patch[token] = value
            continue
        extracted_patch[token] = value

    # Compose bank_details display when split fields were provided.
    bsb = (getattr(invoice, "bank_bsb", None) or "").strip()
    acct = (getattr(invoice, "bank_account", None) or "").strip()
    if bsb or acct:
        extracted_patch["bank_details"] = " · ".join(p for p in (bsb, acct) if p)

    extracted_patch["manual_entry"] = "true"
    merge_invoice_extracted_fields(invoice, extracted_patch)


async def apply_manual_line_items(
    session: AsyncSession,
    invoice: Invoice,
    rows: list[dict[str, Any]],
) -> None:
    """Replace invoice line items from manual capture rows."""
    from sqlalchemy import delete

    from app.models.line_item import LineItem
    from app.services.invoice.invoice_data import ParsedLineItem
    from app.services.shared.amount_sanity import (
        plausible_money,
        plausible_qty,
        sanitize_parsed_line_item,
    )

    if not rows:
        return
    # Explicit delete — never touch invoice.line_items (lazy load breaks async).
    await session.execute(
        delete(LineItem).where(
            LineItem.invoice_id == invoice.id,
            LineItem.tenant_id == invoice.tenant_id,
        )
    )
    await session.flush()
    for row in rows:
        # Mobile form JSON sends numerics as strings; plausible_* coerces them.
        cleaned = sanitize_parsed_line_item(
            ParsedLineItem(
                description=str(row.get("description") or "").strip() or None,
                qty=plausible_qty(row.get("qty")),
                unit_price=plausible_qty(row.get("unit_price")),
                amount=plausible_money(row.get("amount")),
                tax_amount=plausible_money(row.get("tax_amount")),
            )
        )
        if not cleaned.description:
            continue
        session.add(
            LineItem(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                description=cleaned.description,
                qty=cleaned.qty,
                unit_price=cleaned.unit_price,
                amount=cleaned.amount,
                tax_amount=cleaned.tax_amount,
            )
        )
    await session.flush()


def stamp_manual_capture_document_type(
    invoice: Invoice,
    definition: DocumentTypeDefinition,
) -> None:
    invoice.document_type_code = (definition.code or "").strip().upper()
    invoice.document_type_confidence = 1.0
    route = resolved_route_for_definition(definition)
    if route:
        invoice.route_target = route
    kind = document_type_team_expense_kind(definition)
    if kind:
        invoice.team_expense_kind = kind
    set_skip_extraction(invoice)


async def finalize_manual_capture_invoice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice: Invoice,
    definition: DocumentTypeDefinition,
    fields: dict[str, str],
    actor_email: str | None,
    line_items: list[dict[str, Any]] | None = None,
) -> None:
    """Stamp DT, fields, skip-extract flag, and employee identity on a fresh upload row."""
    from app.services.ingest.ingest_fanout_service import (
        stamp_employee_upload_team_expense_fields,
    )

    stamp_manual_capture_document_type(invoice, definition)
    apply_manual_fields_to_invoice(invoice, fields)
    await apply_manual_line_items(session, invoice, list(line_items or []))
    await stamp_employee_upload_team_expense_fields(
        session,
        tenant_id=tenant_id,
        invoice_ids=[invoice.id],
        actor_email=actor_email,
        team_expense_intent=None,
    )
    # Re-apply TE kind from DT after employee stamp (intent path may be empty).
    kind = document_type_team_expense_kind(definition)
    if kind:
        invoice.team_expense_kind = kind
    # Skip-extract never runs OCR T4 refresh — clear sparse-ingest flag so Upload shows the row.
    if getattr(invoice, "duplicate_review_suggested", False):
        invoice.duplicate_review_suggested = False
    await session.flush()


async def create_without_document_invoice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    definition: DocumentTypeDefinition,
    fields: dict[str, str],
    actor_name: str | None,
    actor_email: str | None,
    line_items: list[dict[str, Any]] | None = None,
) -> Invoice:
    """Create a Team Expense / claim row with no file (mobile Without document path).

    Does not ingest a placeholder image — no receipt attachment, no file-hash dedup.
    """
    from app.models.invoice import InvoiceStatus
    from app.models.tenant import Tenant
    from app.services.audit.audit_service import log_event
    from app.services.credit_service import (
        assert_can_upload,
        charge_upload_credits,
    )
    from app.services.dossier.document_ref_service import allocate_next_document_ref
    from app.services.extraction.extraction_field_values import merge_invoice_extracted_fields
    from app.tenant_settings import tenant_currency

    await assert_can_upload(session, tenant_id, pages=1)
    document_ref = await allocate_next_document_ref(session, tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    books_currency = tenant_currency(tenant) if tenant else "AUD"
    field_currency = str((fields or {}).get("currency") or "").strip().upper()
    inv = Invoice(
        tenant_id=tenant_id,
        status=InvoiceStatus.PENDING,
        currency=field_currency or books_currency,
        document_ref=document_ref,
        capture_source="upload",
        uploaded_by_name=(actor_name or "").strip() or None,
        uploaded_by_email=(actor_email or "").strip() or None,
        duplicate_review_suggested=False,
        file_hash=None,
        raw_file_path=None,
        email_attachment_name=None,
        normalized_filename=None,
    )
    session.add(inv)
    await session.flush()

    await finalize_manual_capture_invoice(
        session,
        tenant_id=tenant_id,
        invoice=inv,
        definition=definition,
        fields=fields,
        actor_email=actor_email,
        line_items=line_items,
    )
    merge_invoice_extracted_fields(
        inv,
        {
            "without_document": "true",
            "manual_entry": "true",
        },
    )
    inv.duplicate_review_suggested = False

    await log_event(
        session,
        "invoice_uploaded",
        invoice_id=inv.id,
        detail={
            "without_document": True,
            "document_type_code": (definition.code or "").strip().upper(),
            "capture_source": "upload",
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    await charge_upload_credits(
        session,
        tenant_id,
        pages=1,
        idempotency_key=f"without-doc:{inv.id}",
        invoice_id=inv.id,
        filename="without-document",
        document_ai_provider=None,
    )
    await session.flush()
    return inv
