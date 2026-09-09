"""Ensure QuickBooks Vendor/Customer, currency, tax, and GL lines exist before a later Bill POST."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.contacts import ensure_invoice_qbo_contact
from app.integrations.qbo.currencies import QboCurrencyWriteError, ensure_qbo_currency
from app.integrations.qbo.export_gl import resolve_invoice_qbo_gl_lines
from app.integrations.qbo.store import require_qbo_ready
from app.integrations.qbo.tax_codes import QboTaxCodeWriteError, ensure_invoice_qbo_tax_code
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def ensure_qbo_export_masters(
    db: AsyncSession,
    invoice: Any,
) -> dict[str, Any]:
    """Match/create party, currency, purchase tax, and resolve Bill GL lines. Never raises.

    Contact kind comes from document-type Counterparty type (vendor vs customer).
    Currency uses invoices.currency; Multicurrency must already be on for foreign ISO.
    Tax matches purchase_rate to gst_rate; unmatched % is created (never renamed).
    GL: allotted line sub-ledgers post to QBO subaccounts; unallotted sums post to parent.
    """
    result: dict[str, Any] = {"contact": None, "currency": None, "tax": None, "gl": None}
    try:
        await require_qbo_ready(db, invoice.tenant_id)
    except Exception:
        return result

    try:
        result["contact"] = await ensure_invoice_qbo_contact(db, invoice)
    except Exception:
        logger.warning(
            "qbo_export_contact_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            exc_info=True,
        )

    raw = (getattr(invoice, "currency", None) or "").strip()
    if raw:
        try:
            row = await ensure_qbo_currency(db, tenant_id=invoice.tenant_id, code=raw)
            result["currency"] = {"code": row.code, "name": row.name}
        except QboCurrencyWriteError as exc:
            logger.warning(
                "qbo_export_currency_ensure_failed",
                invoice_id=getattr(invoice, "id", None),
                currency=raw,
                error=exc.message,
                status_code=exc.status_code,
            )
        except Exception:
            logger.warning(
                "qbo_export_currency_ensure_failed",
                invoice_id=getattr(invoice, "id", None),
                currency=raw,
                exc_info=True,
            )

    try:
        result["tax"] = await ensure_invoice_qbo_tax_code(db, invoice)
    except QboTaxCodeWriteError as exc:
        logger.warning(
            "qbo_export_tax_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            error=exc.message,
            status_code=exc.status_code,
        )
    except Exception:
        logger.warning(
            "qbo_export_tax_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            exc_info=True,
        )

    try:
        result["gl"] = await resolve_invoice_qbo_gl_lines(db, invoice)
    except Exception:
        logger.warning(
            "qbo_export_gl_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            exc_info=True,
        )
    return result
