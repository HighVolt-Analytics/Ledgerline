"""Production Xero supplier-bill export pipeline (ACCPAY Draft + attachment)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_entity_mapping import (
    MAPPING_GL_ACCOUNT,
    MAPPING_TRACKING,
)
from app.models.accounting_export_ledger import (
    ATTACHMENT_FAILED,
    ATTACHMENT_MISSING,
    ATTACHMENT_PENDING,
    ATTACHMENT_SUCCESS,
    DIRECTION_OUTBOUND,
    PROVIDER_XERO,
    STATUS_FAILED_TERMINAL,
    STATUS_HUMAN_REVIEW,
    STATUS_IN_FLIGHT,
    STATUS_READY,
    STATUS_RETRY_PENDING,
    STATUS_SUCCESS,
    TXN_SUPPLIER_INVOICE,
    AccountingExportLedger,
)
from app.models.external_accounting_ref import ExternalAccountingRef
from app.models.invoice import InvoiceStatus
from app.models.xero_currency import XeroCurrency
from app.schemas.canonical_accounting_transaction import CanonicalTracking
from app.integrations.xero.accpay import (
    assert_draft_status,
    build_accpay_draft_payload,
    validate_accpay_payload,
)
from app.integrations.xero.attachments import upload_invoice_pdf_attachment
from app.integrations.xero.client import XeroApiClient, XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.services.integration.accounting_mapping_service import get_mapping
from app.services.integration.canonical_transaction_builder import (
    CanonicalTransactionError,
    assert_canonical_valid,
    build_canonical_supplier_invoice,
    load_invoice_for_export,
    resolve_organisation_posting_currency,
)
from app.integrations.xero.contacts import (
    resolve_supplier_contact,
    save_supplier_contact_mapping,
)
from app.integrations.xero.tax_rates import resolve_invoice_xero_tax_type
from app.integrations.xero.errors import (
    ERROR_TERMINAL,
    ERROR_TRANSIENT,
    classify_error,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.utils.logger import correlation_id_ctx, get_logger

logger = get_logger(__name__)

_IN_FLIGHT_BACKOFF = timedelta(minutes=2)
_ENTITY_TYPE_INVOICE = "invoice"


class XeroExportError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "export_failed",
        bucket: str = ERROR_TERMINAL,
        blocking_errors: list[dict[str, str]] | None = None,
        ledger: AccountingExportLedger | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.bucket = bucket
        self.blocking_errors = blocking_errors or []
        self.ledger = ledger


def ledger_to_dict(row: AccountingExportLedger) -> dict[str, Any]:
    return {
        "sync_id": row.id,
        "id": row.id,
        "tenant_id": str(row.tenant_id),
        "provider": row.provider,
        "qll_transaction_id": row.qll_transaction_id,
        "source_invoice_id": row.source_invoice_id,
        "source_document_id": row.source_document_id,
        "transaction_type": row.transaction_type,
        "direction": row.direction,
        "status": row.status,
        "payload_version": row.payload_version,
        "payload_hash": row.payload_hash,
        "idempotency_key": row.idempotency_key,
        "external_id": row.external_id,
        "external_number": row.external_number,
        "external_status": row.external_status,
        "external_contact_id": row.external_contact_id,
        "external_currency": row.external_currency,
        "external_total": float(row.external_total) if row.external_total is not None else None,
        "xero_tenant_id": row.xero_tenant_id,
        "attempt_count": row.attempt_count,
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "error_bucket": row.error_bucket,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "request_correlation_id": row.request_correlation_id,
        "last_response_summary": row.last_response_summary,
        "attachment_status": row.attachment_status,
        "attachment_external_id": row.attachment_external_id,
        "attachment_error": row.attachment_error,
        "amount_due": float(row.amount_due) if row.amount_due is not None else None,
        "amount_paid": float(row.amount_paid) if row.amount_paid is not None else None,
        "is_fully_paid": row.is_fully_paid,
        "divergence_flags": (
            json.loads(row.divergence_flags_json) if row.divergence_flags_json else []
        ),
        "last_refreshed_at": row.last_refreshed_at.isoformat()
        if row.last_refreshed_at
        else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "export_complete": row.status == STATUS_SUCCESS
        and row.attachment_status == ATTACHMENT_SUCCESS,
    }


async def _latest_ledger_for_invoice(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    for_update: bool = False,
) -> AccountingExportLedger | None:
    stmt = (
        select(AccountingExportLedger)
        .where(
            AccountingExportLedger.tenant_id == tenant_id,
            AccountingExportLedger.provider == PROVIDER_XERO,
            AccountingExportLedger.source_invoice_id == invoice_id,
        )
        .order_by(
            AccountingExportLedger.payload_version.desc(),
            AccountingExportLedger.id.desc(),
        )
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_export_ledger(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    sync_id: int,
) -> AccountingExportLedger | None:
    return (
        await db.execute(
            select(AccountingExportLedger).where(
                AccountingExportLedger.id == sync_id,
                AccountingExportLedger.tenant_id == tenant_id,
                AccountingExportLedger.provider == PROVIDER_XERO,
            )
        )
    ).scalar_one_or_none()


async def list_export_ledger(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> dict[str, Any]:
    stmt = select(AccountingExportLedger).where(
        AccountingExportLedger.tenant_id == tenant_id,
        AccountingExportLedger.provider == PROVIDER_XERO,
    )
    if status:
        stmt = stmt.where(AccountingExportLedger.status == status)
    total = len((await db.execute(stmt)).scalars().all())
    rows = (
        await db.execute(
            stmt.order_by(AccountingExportLedger.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {"items": [ledger_to_dict(r) for r in rows], "total": total}


async def validate_invoice_for_xero_export(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> dict[str, Any]:
    """Validate mappings / contact / totals without calling Xero write APIs."""
    blocking: list[dict[str, str]] = []
    try:
        invoice = await load_invoice_for_export(
            db, tenant_id=tenant_id, invoice_id=invoice_id
        )
    except CanonicalTransactionError as exc:
        return {
            "valid": False,
            "invoice_id": invoice_id,
            "blocking_errors": [
                {"field": "invoice", "code": exc.code, "message": str(exc)}
            ],
            "canonical": None,
        }

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        blocking.append(
            {
                "field": "transaction_type",
                "code": "accrec_not_supported",
                "message": "ACCREC customer invoices are not supported in Phase 1",
            }
        )

    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)

    supplier_key = str(invoice.storage_vendor_slug or invoice.vendor or invoice.id)
    gl_key = (invoice.account_code or "").strip()
    gl_map = (
        await get_mapping(
            db,
            tenant_id=tenant_id,
            mapping_type=MAPPING_GL_ACCOUNT,
            source_key=gl_key,
            xero_tenant_id=xero_tenant_id,
        )
        if gl_key
        else None
    )
    mapped_account = (gl_map.external_code if gl_map else None) or gl_key or None

    mapped_tax = await resolve_invoice_xero_tax_type(
        db,
        tenant_id=tenant_id,
        xero_tenant_id=xero_tenant_id,
        invoice=invoice,
    )

    tracking_list: list[CanonicalTracking] = []
    cost_centre = (invoice.cost_centre or "").strip()
    if cost_centre:
        track_map = await get_mapping(
            db,
            tenant_id=tenant_id,
            mapping_type=MAPPING_TRACKING,
            source_key=cost_centre,
            xero_tenant_id=xero_tenant_id,
        )
        if track_map is None:
            blocking.append(
                {
                    "field": "tracking",
                    "code": "tracking_option_missing",
                    "message": "tracking option missing",
                }
            )
        else:
            tracking_list.append(
                CanonicalTracking(
                    category_name=track_map.external_name,
                    option_name=track_map.source_label or cost_centre,
                    mapped_xero_tracking_category_id=track_map.external_id,
                    mapped_xero_tracking_option_id=track_map.external_option_id,
                )
            )

    contact_match = await resolve_supplier_contact(
        db,
        tenant_id=tenant_id,
        xero_tenant_id=xero_tenant_id,
        supplier_key=supplier_key,
        legal_name=invoice.vendor or "",
        tax_id=invoice.abn,
        email=invoice.email_sender,
    )
    if contact_match.outcome == "ambiguous":
        blocking.append(
            {
                "field": "supplier",
                "code": "ambiguous_supplier_match",
                "message": "ambiguous supplier match ΓÇö human review required",
            }
        )
    elif contact_match.outcome == "none" or not contact_match.contact_id:
        # Exact match missing: export will auto-create when legal name is present.
        if not (invoice.vendor or "").strip():
            blocking.append(
                {
                    "field": "supplier",
                    "code": "contact_not_mapped",
                    "message": "supplier has no Xero contact and no legal name to create one",
                }
            )

    if not mapped_account:
        blocking.append(
            {
                "field": "account_code",
                "code": "account_not_mapped",
                "message": "GL account not mapped",
            }
        )

    currency = await resolve_organisation_posting_currency(
        db,
        tenant_id=tenant_id,
        xero_tenant_id=xero_tenant_id,
        invoice_id=invoice_id,
    )
    if not currency:
        blocking.append(
            {
                "field": "currency",
                "code": "currency_missing",
                "message": "Document currency is missing",
            }
        )
    else:
        currency_row = (
            await db.execute(
                select(XeroCurrency).where(
                    XeroCurrency.tenant_id == tenant_id,
                    XeroCurrency.xero_tenant_id == xero_tenant_id,
                    XeroCurrency.code == currency,
                    XeroCurrency.sync_status == "active",
                )
            )
        ).scalar_one_or_none()
        if currency_row is None:
            blocking.append(
                {
                    "field": "currency",
                    "code": "currency_not_supported",
                    "message": f"Document currency '{currency}' is not supported by the selected Xero organisation",
                }
            )

    txn = build_canonical_supplier_invoice(
        invoice,
        tenant_id=tenant_id,
        posting_currency=currency or "",
        external_xero_contact_id=contact_match.contact_id,
        mapped_account_code=mapped_account,
        mapped_tax_type=mapped_tax,
        tracking=tracking_list,
    )
    blocking.extend(assert_canonical_valid(txn))

    if contact_match.contact_id:
        payload = build_accpay_draft_payload(txn, contact_id=contact_match.contact_id)
        if invoice.invoice_no:
            payload["InvoiceNumber"] = invoice.invoice_no
        blocking.extend(validate_accpay_payload(payload))

    return {
        "valid": not blocking,
        "invoice_id": invoice_id,
        "xero_organisation_id": integration.provider_tenant_id or xero_tenant_id,
        "contact_resolution": {
            "outcome": contact_match.outcome,
            "contact_id": contact_match.contact_id,
            "reason": contact_match.reason,
            "candidates": contact_match.candidates,
        },
        "blocking_errors": blocking,
        "canonical": txn.model_dump_serialisable(),
    }


async def export_supplier_invoice_to_xero(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Idempotent ACCPAY Draft export with sync-ledger lock and PDF attachment."""
    now = datetime.now(timezone.utc)
    correlation_id = correlation_id_ctx.get() or str(uuid.uuid4())

    validation = await validate_invoice_for_xero_export(
        db, tenant_id=tenant_id, invoice_id=invoice_id
    )
    if not validation["valid"]:
        # Ambiguous supplier ΓåÆ human review ledger row
        codes = {e.get("code") for e in validation["blocking_errors"]}
        if "ambiguous_supplier_match" in codes:
            ledger = await _ensure_review_ledger(
                db,
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                validation=validation,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            raise XeroExportError(
                "ambiguous supplier match",
                code="ambiguous_supplier_match",
                bucket=STATUS_HUMAN_REVIEW,
                blocking_errors=validation["blocking_errors"],
                ledger=ledger,
            )
        raise XeroExportError(
            "Export validation failed",
            code="validation_failed",
            bucket=ERROR_TERMINAL,
            blocking_errors=validation["blocking_errors"],
        )

    invoice = await load_invoice_for_export(
        db, tenant_id=tenant_id, invoice_id=invoice_id
    )
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    del integration

    from app.schemas.canonical_accounting_transaction import (
        CanonicalAccountingTransaction,
    )
    from app.integrations.xero.contacts import (
        create_xero_supplier_contact,
    )

    canonical_data = validation["canonical"]
    txn = CanonicalAccountingTransaction.model_validate(canonical_data)
    contact_id = validation["contact_resolution"]["contact_id"]
    outcome = validation["contact_resolution"]["outcome"]

    if not contact_id and outcome == "none":
        try:
            created = await create_xero_supplier_contact(
                db,
                tenant_id=tenant_id,
                supplier_key=str(
                    invoice.storage_vendor_slug or invoice.vendor or invoice.id
                ),
                legal_name=invoice.vendor or "",
                tax_id=invoice.abn,
                email=invoice.email_sender,
                user_id=user_id,
            )
        except ValueError as exc:
            if str(exc) == "ambiguous_supplier_match":
                ledger = await _ensure_review_ledger(
                    db,
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    validation=validation,
                    user_id=user_id,
                    correlation_id=correlation_id,
                )
                raise XeroExportError(
                    "ambiguous supplier match",
                    code="ambiguous_supplier_match",
                    bucket=STATUS_HUMAN_REVIEW,
                    blocking_errors=[
                        {
                            "field": "supplier",
                            "code": "ambiguous_supplier_match",
                            "message": "ambiguous supplier match ΓÇö human review required",
                        }
                    ],
                    ledger=ledger,
                ) from exc
            raise XeroExportError(
                str(exc) or "supplier create failed",
                code="supplier_create_failed",
                bucket=ERROR_TERMINAL,
            ) from exc
        except XeroApiError as exc:
            raise XeroExportError(
                exc.message or "supplier create failed",
                code=exc.error_code or "supplier_create_failed",
                bucket=ERROR_TRANSIENT if (exc.status_code or 500) >= 500 else ERROR_TERMINAL,
            ) from exc
        contact_id = created["contact_id"]
        outcome = "created" if created.get("created") else "matched"
        txn.supplier.external_xero_contact_id = contact_id

    assert contact_id

    # Persist mapping evidence for exact match or newly created supplier.
    if outcome in {"matched", "created"}:
        await save_supplier_contact_mapping(
            db,
            tenant_id=tenant_id,
            supplier_key=str(invoice.storage_vendor_slug or invoice.vendor or invoice.id),
            legal_name=invoice.vendor or "",
            contact_id=contact_id,
            user_id=user_id,
            xero_tenant_id=xero_tenant_id,
        )

    payload = build_accpay_draft_payload(txn, contact_id=contact_id)
    if invoice.invoice_no:
        payload["InvoiceNumber"] = invoice.invoice_no
    assert_draft_status(payload)

    ledger = await _latest_ledger_for_invoice(
        db, tenant_id=tenant_id, invoice_id=invoice_id, for_update=True
    )

    if ledger and ledger.status == STATUS_SUCCESS and ledger.payload_hash == txn.payload_hash:
        # Same payload ╬ô├ç├╢ return evidence; retry attachment only if needed.
        if ledger.attachment_status != ATTACHMENT_SUCCESS and txn.attachment:
            await _attach_pdf(db, ledger=ledger, txn=txn, xero_tenant_id=xero_tenant_id)
            await db.refresh(ledger)
        return {
            "skipped": True,
            "reason": "already_exported",
            "evidence": ledger_to_dict(ledger),
        }

    if (
        ledger
        and ledger.status == STATUS_IN_FLIGHT
        and ledger.last_attempt_at
        and now - ledger.last_attempt_at < _IN_FLIGHT_BACKOFF
    ):
        raise XeroExportError(
            "Export already in flight",
            code="in_flight",
            bucket=ERROR_TRANSIENT,
            ledger=ledger,
        )

    if ledger and ledger.payload_hash != txn.payload_hash and ledger.external_id:
        # Changed payload after success requires a new version row.
        ledger = AccountingExportLedger(
            tenant_id=tenant_id,
            provider=PROVIDER_XERO,
            qll_transaction_id=txn.qll_transaction_id,
            source_invoice_id=invoice_id,
            source_document_id=txn.source_document_id,
            transaction_type=TXN_SUPPLIER_INVOICE,
            direction=DIRECTION_OUTBOUND,
            status=STATUS_READY,
            payload_version=(ledger.payload_version or 1) + 1,
            payload_hash=txn.payload_hash,
            idempotency_key=f"{txn.idempotency_key}:v{(ledger.payload_version or 1) + 1}",
            canonical_json=txn.model_dump_json(),
            created_by=user_id,
        )
        db.add(ledger)
        await db.flush()
    elif ledger is None:
        ledger = AccountingExportLedger(
            tenant_id=tenant_id,
            provider=PROVIDER_XERO,
            qll_transaction_id=txn.qll_transaction_id,
            source_invoice_id=invoice_id,
            source_document_id=txn.source_document_id,
            transaction_type=TXN_SUPPLIER_INVOICE,
            direction=DIRECTION_OUTBOUND,
            status=STATUS_READY,
            payload_version=txn.payload_version,
            payload_hash=txn.payload_hash,
            idempotency_key=txn.idempotency_key,
            canonical_json=txn.model_dump_json(),
            created_by=user_id,
        )
        db.add(ledger)
        await db.flush()
    else:
        # Reuse ready/retry/failed row for same payload.
        ledger.qll_transaction_id = txn.qll_transaction_id
        ledger.payload_hash = txn.payload_hash
        ledger.idempotency_key = txn.idempotency_key
        ledger.canonical_json = txn.model_dump_json()

    ledger.status = STATUS_IN_FLIGHT
    ledger.attempt_count = int(ledger.attempt_count or 0) + 1
    ledger.last_attempt_at = now
    ledger.request_correlation_id = correlation_id
    ledger.xero_tenant_id = xero_tenant_id
    ledger.request_payload_json = json.dumps(payload, default=str)
    ledger.error_bucket = None
    ledger.error_code = None
    ledger.error_message = None
    if txn.attachment:
        ledger.attachment_status = ATTACHMENT_PENDING
    else:
        ledger.attachment_status = ATTACHMENT_MISSING
    await db.flush()

    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    try:
        response = await client.post_json("Invoices", json_body={"Invoices": [payload]})
        invoices = response.get("Invoices") or []
        if not invoices:
            raise XeroApiError(
                500,
                "Xero returned no invoice payload",
                error_code="empty_response",
            )
        created = invoices[0]
        ledger.external_id = str(created.get("InvoiceID") or "")
        ledger.external_number = created.get("InvoiceNumber")
        ledger.external_status = created.get("Status") or "DRAFT"
        ledger.external_contact_id = contact_id
        ledger.external_currency = created.get("CurrencyCode") or txn.currency
        total = created.get("Total")
        ledger.external_total = Decimal(str(total)) if total is not None else txn.total
        ledger.last_response_summary = json.dumps(
            {
                "InvoiceID": ledger.external_id,
                "InvoiceNumber": ledger.external_number,
                "Status": ledger.external_status,
                "Total": str(ledger.external_total),
            },
            default=str,
        )[:2000]
        ledger.status = STATUS_SUCCESS
        await db.flush()

        await _mirror_external_ref(db, ledger=ledger, invoice=invoice)

        attachment_result = None
        if txn.attachment and ledger.external_id:
            attachment_result = await _attach_pdf(
                db, ledger=ledger, txn=txn, xero_tenant_id=xero_tenant_id
            )

        await db.refresh(ledger)
        return {
            "skipped": False,
            "evidence": ledger_to_dict(ledger),
            "attachment": attachment_result,
            "xero_payload": payload,
        }
    except XeroApiError as exc:
        classified = classify_error(exc=exc)
        ledger.error_bucket = classified.bucket
        ledger.error_code = classified.code
        ledger.error_message = classified.message
        if classified.retryable:
            ledger.status = STATUS_RETRY_PENDING
            ledger.next_retry_at = now + timedelta(minutes=min(2 ** ledger.attempt_count, 60))
        else:
            ledger.status = STATUS_FAILED_TERMINAL
            ledger.next_retry_at = None
        await db.flush()
        raise XeroExportError(
            classified.message,
            code=classified.code,
            bucket=classified.bucket,
            ledger=ledger,
        ) from exc


async def _attach_pdf(
    db: AsyncSession,
    *,
    ledger: AccountingExportLedger,
    txn: Any,
    xero_tenant_id: str,
) -> dict[str, Any] | None:
    if not txn.attachment or not ledger.external_id:
        ledger.attachment_status = ATTACHMENT_MISSING
        await db.flush()
        return None
    try:
        result = await upload_invoice_pdf_attachment(
            db,
            tenant_id=ledger.tenant_id,
            xero_tenant_id=xero_tenant_id,
            xero_invoice_id=ledger.external_id,
            storage_locator=txn.attachment.storage_locator,
            filename=txn.attachment.filename,
        )
        ledger.attachment_status = ATTACHMENT_SUCCESS
        ledger.attachment_external_id = result.get("attachment_id")
        ledger.attachment_error = None
        await db.flush()
        return result
    except XeroApiError as exc:
        classified = classify_error(exc=exc)
        ledger.attachment_status = ATTACHMENT_FAILED
        ledger.attachment_error = classified.message
        await db.flush()
        return {
            "ok": False,
            "error_bucket": classified.bucket,
            "error_code": classified.code,
            "error_message": classified.message,
        }


async def retry_attachment(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    sync_id: int,
) -> dict[str, Any]:
    ledger = await get_export_ledger(db, tenant_id=tenant_id, sync_id=sync_id)
    if ledger is None:
        raise XeroExportError("Export not found", code="not_found")
    if not ledger.external_id:
        raise XeroExportError(
            "Cannot retry attachment without an exported Xero bill",
            code="invalid_payload",
        )
    if not ledger.canonical_json:
        raise XeroExportError("Canonical payload missing", code="invalid_payload")
    from app.schemas.canonical_accounting_transaction import (
        CanonicalAccountingTransaction,
    )

    txn = CanonicalAccountingTransaction.model_validate_json(ledger.canonical_json)
    xero_tenant_id = ledger.xero_tenant_id
    if not xero_tenant_id:
        _, xero_tenant_id = await require_xero_ready(db, tenant_id)
    result = await _attach_pdf(
        db, ledger=ledger, txn=txn, xero_tenant_id=xero_tenant_id
    )
    await db.refresh(ledger)
    return {"evidence": ledger_to_dict(ledger), "attachment": result}


async def refresh_export_from_xero(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    sync_id: int,
) -> dict[str, Any]:
    ledger = await get_export_ledger(db, tenant_id=tenant_id, sync_id=sync_id)
    if ledger is None or not ledger.external_id:
        raise XeroExportError("Export not found or missing external id", code="not_found")
    _, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroApiClient(
        db=db,
        tenant_id=tenant_id,
        xero_tenant_id=ledger.xero_tenant_id or xero_tenant_id,
    )
    payload = await client.get_json("Invoices", params={"IDs": ledger.external_id})
    invoices = payload.get("Invoices") or []
    if not invoices:
        raise XeroExportError("Xero invoice not found", code="not_found")
    remote = invoices[0]
    now = datetime.now(timezone.utc)
    ledger.external_status = remote.get("Status")
    ledger.external_number = remote.get("InvoiceNumber") or ledger.external_number
    if remote.get("Total") is not None:
        ledger.external_total = Decimal(str(remote.get("Total")))
    if remote.get("AmountDue") is not None:
        ledger.amount_due = Decimal(str(remote.get("AmountDue")))
    if remote.get("AmountPaid") is not None:
        ledger.amount_paid = Decimal(str(remote.get("AmountPaid")))
    ledger.is_fully_paid = bool(remote.get("FullyPaidOnDate")) or (
        ledger.amount_due is not None and ledger.amount_due == 0
    )
    flags: list[str] = []
    if ledger.canonical_json:
        from app.schemas.canonical_accounting_transaction import (
            CanonicalAccountingTransaction,
        )

        txn = CanonicalAccountingTransaction.model_validate_json(ledger.canonical_json)
        if ledger.external_total is not None and abs(
            Decimal(str(ledger.external_total)) - txn.total
        ) > Decimal("0.02"):
            flags.append("total_mismatch")
        if (ledger.external_status or "").upper() not in {"DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED"}:
            flags.append("unexpected_status")
        if (ledger.external_status or "").upper() == "VOIDED":
            flags.append("voided")
    ledger.divergence_flags_json = json.dumps(flags)
    ledger.last_refreshed_at = now
    ledger.last_remote_modified_at = now
    await db.flush()
    return {"evidence": ledger_to_dict(ledger), "remote": remote, "divergence_flags": flags}


async def _ensure_review_ledger(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    validation: dict[str, Any],
    user_id: int | None,
    correlation_id: str,
) -> AccountingExportLedger:
    canonical = validation.get("canonical") or {}
    qll_id = canonical.get("qll_transaction_id") or str(uuid.uuid4())
    payload_hash = canonical.get("payload_hash") or "review"
    ledger = await _latest_ledger_for_invoice(
        db, tenant_id=tenant_id, invoice_id=invoice_id
    )
    if ledger is None:
        ledger = AccountingExportLedger(
            tenant_id=tenant_id,
            provider=PROVIDER_XERO,
            qll_transaction_id=qll_id,
            source_invoice_id=invoice_id,
            transaction_type=TXN_SUPPLIER_INVOICE,
            direction=DIRECTION_OUTBOUND,
            status=STATUS_HUMAN_REVIEW,
            payload_version=1,
            payload_hash=payload_hash,
            idempotency_key=f"review:{invoice_id}:{payload_hash[:16]}",
            canonical_json=json.dumps(canonical, default=str),
            created_by=user_id,
        )
        db.add(ledger)
    ledger.status = STATUS_HUMAN_REVIEW
    ledger.error_bucket = ERROR_TERMINAL
    ledger.error_code = "ambiguous_supplier_match"
    ledger.error_message = "ambiguous supplier match"
    ledger.request_correlation_id = correlation_id
    await db.flush()
    return ledger


async def _mirror_external_ref(
    db: AsyncSession,
    *,
    ledger: AccountingExportLedger,
    invoice: Any,
) -> None:
    """Keep legacy ExternalAccountingRef in sync for existing UI/history."""
    ref = (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == ledger.tenant_id,
                ExternalAccountingRef.provider == PROVIDER_XERO,
                ExternalAccountingRef.entity_type == _ENTITY_TYPE_INVOICE,
                ExternalAccountingRef.internal_entity_id == str(ledger.source_invoice_id),
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if ref is None:
        ref = ExternalAccountingRef(
            tenant_id=ledger.tenant_id,
            provider=PROVIDER_XERO,
            entity_type=_ENTITY_TYPE_INVOICE,
            internal_entity_id=str(ledger.source_invoice_id),
            external_entity_id=ledger.external_id or "",
        )
        db.add(ref)
    ref.external_entity_id = ledger.external_id or ""
    ref.external_number = ledger.external_number
    ref.external_status = ledger.external_status
    ref.payload_hash = ledger.payload_hash
    ref.last_pushed_at = now
    ref.last_synced_at = now
    ref.sync_status = "synced"
    ref.sync_direction = "outbound"
    ref.source_system = "ledgerlink"
    ref.metadata_json = json.dumps(
        {
            "xero_type": "ACCPAY",
            "sync_id": ledger.id,
            "qll_transaction_id": ledger.qll_transaction_id,
            "route_target": getattr(invoice, "route_target", None),
        }
    )
    await db.flush()


# Back-compat wrapper used by older push route / JournalExportTab.
async def push_invoice_to_xero_pipeline(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    user_id: int,
) -> dict[str, Any]:
    result = await export_supplier_invoice_to_xero(
        db, tenant_id=tenant_id, invoice_id=invoice_id, user_id=user_id
    )
    evidence = result["evidence"]
    return {
        "invoice_id": invoice_id,
        "skipped": result.get("skipped", False),
        "reason": result.get("reason"),
        "external_entity_id": evidence.get("external_id"),
        "external_number": evidence.get("external_number"),
        "external_status": evidence.get("external_status"),
        "xero_type": "ACCPAY",
        "synced": evidence.get("status") == STATUS_SUCCESS,
        "committed": False,
        "attachment_status": evidence.get("attachment_status"),
        "sync_id": evidence.get("sync_id"),
        "export_complete": evidence.get("export_complete"),
        "evidence": evidence,
    }
