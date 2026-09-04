"""Manual field edits for invoices in the approval queue."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.invoice import InvoiceUpdateRequest
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_data import ParsedLineItem
from app.services.invoice.processing_override_catalog import (
    normalise_processing_overrides,
    serialise_processing_overrides,
    validate_skip_steps,
)
from app.services.shared.amount_sanity import (
    plausible_confidence,
    plausible_gst_rate_percent,
    plausible_money,
    plausible_qty,
    sanitize_parsed_line_item,
)
from app.services.shared.bank_masking import drop_masked_bank_values

_EDITABLE = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)


def _currency_is_unset(value: object) -> bool:
    token = str(value or "").strip().upper()
    return not (len(token) == 3 and token.isalpha())


def _is_currency_fill_only(inv: Invoice, payload: dict) -> bool:
    """Allow setting ISO currency when it was never extracted, on any status."""
    if set(payload.keys()) != {"currency"}:
        return False
    if not _currency_is_unset(inv.currency):
        return False
    raw = payload.get("currency")
    if not isinstance(raw, str):
        return False
    next_code = raw.strip().upper()
    return len(next_code) == 3 and next_code.isalpha()


def _serialise(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


async def refresh_invoice_evaluation_after_edit(
    session: AsyncSession,
    inv: Invoice,
    *,
    enqueue_pending: bool = True,
) -> None:
    """Re-run routing/vendor evaluation after clerk field corrections."""
    from app.services.invoice.invoice_evaluation_service import (
        apply_invoice_evaluation,
        load_config_for_tenant,
    )

    config = await load_config_for_tenant(session, inv.tenant_id)
    await apply_invoice_evaluation(
        session,
        inv,
        config=config,
        enqueue_pending=enqueue_pending,
    )


async def update_invoice_fields(
    session: AsyncSession,
    inv: Invoice,
    body: InvoiceUpdateRequest,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> bool:
    payload = body.model_dump(exclude_unset=True)
    currency_fill_only = _is_currency_fill_only(inv, payload)
    if inv.status not in _EDITABLE and not currency_fill_only:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot be edited; "
            "only exception, duplicate, or rejected invoices in the review queue"
        )

    line_items_payload = payload.pop("line_items", None)
    overrides_explicit = "processing_overrides" in body.model_fields_set
    overrides_payload = (
        payload.pop("processing_overrides", None) if overrides_explicit else None
    )
    overrides_requested = overrides_explicit
    extracted_fields_payload = payload.pop("extracted_fields", None)
    if extracted_fields_payload is not None:
        extracted_fields_payload = drop_masked_bank_values(extracted_fields_payload)
    payload = drop_masked_bank_values(payload)
    changes: dict[str, dict[str, str | None]] = {}

    for field, value in payload.items():
        if field in {"subtotal", "gst", "total"}:
            value = plausible_money(value)
        elif field == "gst_rate":
            value = plausible_gst_rate_percent(value)
        elif field == "currency":
            # invoices.currency is NOT NULL; empty string means "unset ISO".
            if value is None:
                value = ""
            elif isinstance(value, str):
                value = value.strip().upper() or ""
        old = getattr(inv, field)
        if old != value:
            changes[field] = {"from": _serialise(old), "to": _serialise(value)}
            setattr(inv, field, value)
            # User-confirmed ISO replaces ambiguous symbol-only display hint.
            if field == "currency" and value:
                fields = dict(inv.extracted_fields or {})
                if fields.pop("currency_symbol", None) is not None:
                    inv.extracted_fields = fields

    if extracted_fields_payload is not None:
        from app.services.extraction.extraction_field_values import merge_invoice_extracted_fields

        old_fields = dict(inv.extracted_fields or {})
        merge_invoice_extracted_fields(inv, extracted_fields_payload)
        new_fields = dict(inv.extracted_fields or {})
        field_changes: dict[str, dict[str, str | None]] = {}
        for key in set(old_fields) | set(new_fields):
            before = old_fields.get(key)
            after = new_fields.get(key)
            if before != after:
                field_changes[key] = {"from": before, "to": after}
        if field_changes:
            changes["extracted_fields"] = {
                "from": _serialise({k: old_fields.get(k) for k in field_changes}),
                "to": _serialise({k: new_fields.get(k) for k in field_changes}),
            }

    if line_items_payload is not None:
        old_count = len(inv.line_items)
        for li in list(inv.line_items):
            await session.delete(li)
        await session.flush()

        for item in line_items_payload:
            parent_ledger = item.get("parent_ledger")
            if isinstance(parent_ledger, str):
                parent_ledger = parent_ledger.strip() or None
            gl_source = item.get("gl_mapping_source")
            if isinstance(gl_source, str):
                gl_source = gl_source.strip() or None
            sub_ledger = item.get("sub_ledger")
            if isinstance(sub_ledger, str):
                token = sub_ledger.strip()
                if token.lower() in {"__none__", "none"}:
                    sub_ledger = None
                    gl_source = gl_source or "manual"
                else:
                    sub_ledger = token or None
            if (sub_ledger is not None or parent_ledger is not None) and not gl_source:
                gl_source = "manual"
            cleaned = sanitize_parsed_line_item(
                ParsedLineItem(
                    description=item.get("description"),
                    qty=plausible_qty(item.get("qty")),
                    unit_price=plausible_money(item.get("unit_price")),
                    amount=plausible_money(item.get("amount")),
                    tax_amount=plausible_money(item.get("tax_amount")),
                )
            )
            session.add(
                LineItem(
                    tenant_id=inv.tenant_id,
                    invoice_id=inv.id,
                    description=cleaned.description,
                    qty=cleaned.qty,
                    unit_price=cleaned.unit_price,
                    amount=cleaned.amount,
                    tax_amount=cleaned.tax_amount,
                    sub_ledger=sub_ledger,
                    parent_ledger=parent_ledger,
                    gl_mapping_source=gl_source,
                    gl_mapping_confidence=plausible_confidence(item.get("gl_mapping_confidence")),
                    gl_mapping_reason=item.get("gl_mapping_reason"),
                )
            )
        changes["line_items"] = {
            "from": str(old_count),
            "to": str(len(line_items_payload)),
        }

    if overrides_requested:
        if overrides_payload is None:
            old_norm = normalise_processing_overrides(inv.processing_overrides)
            if old_norm.skip_steps:
                inv.processing_overrides = None
                await session.flush()
                await log_event(
                    session,
                    "processing_overrides_updated",
                    invoice_id=inv.id,
                    detail={
                        "from": old_norm.skip_steps,
                        "to": [],
                    },
                    actor_name=actor_name,
                    actor_email=actor_email,
                )
                changes["processing_overrides"] = {
                    "from": ",".join(old_norm.skip_steps) or None,
                    "to": None,
                }
        else:
            skip_steps = validate_skip_steps(list(overrides_payload.get("skip_steps") or []))
            new_raw = serialise_processing_overrides(skip_steps)
            old_norm = normalise_processing_overrides(inv.processing_overrides)
            new_norm = normalise_processing_overrides(new_raw)
            if old_norm.skip_steps != new_norm.skip_steps:
                inv.processing_overrides = new_raw
                await session.flush()
                await log_event(
                    session,
                    "processing_overrides_updated",
                    invoice_id=inv.id,
                    detail={
                        "from": old_norm.skip_steps,
                        "to": new_norm.skip_steps,
                    },
                    actor_name=actor_name,
                    actor_email=actor_email,
                )
                changes["processing_overrides"] = {
                    "from": ",".join(old_norm.skip_steps) or None,
                    "to": ",".join(new_norm.skip_steps) or None,
                }

    if not changes:
        return False

    await session.flush()

    # After clerk fills DT-required fields, drop sticky vision needs_review
    # so Confirm & process is not blocked by a stale extract flag.
    from app.services.classification.document_type_catalog import get_document_type_definition
    from app.services.invoice.invoice_evaluation_service import (
        EVAL_VISION_HEADER_REVIEW,
        load_config_for_tenant,
    )
    from app.services.invoice.vision_posting_continue import vision_header_ok_from_invoice

    if (inv.evaluation_status or "").strip() == EVAL_VISION_HEADER_REVIEW:
        config = await load_config_for_tenant(session, inv.tenant_id)
        definition = get_document_type_definition(
            inv.document_type_code,
            document_types=config.document_types,
        )
        vision_header_ok_from_invoice(inv, definition)

    await log_event(
        session,
        "invoice_fields_updated",
        invoice_id=inv.id,
        detail={"changes": changes},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return True


async def invoice_has_manual_field_edits(
    session: AsyncSession,
    invoice_id: int,
    *,
    tenant_id: uuid.UUID,
) -> bool:
    """True when a clerk saved field corrections on this invoice in the current cycle."""
    from app.services.invoice.processing_cycle_service import (
        has_audit_event_after_cycle_reset,
    )

    return await has_audit_event_after_cycle_reset(
        session,
        invoice_id,
        event="invoice_fields_updated",
        tenant_id=tenant_id,
    )
