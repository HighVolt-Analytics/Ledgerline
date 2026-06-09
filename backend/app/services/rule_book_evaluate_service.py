"""Evaluate rule book against organisation documents."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.services.capture_channel import infer_capture_channel
from app.services.rule_engine import (
    EvalDocument,
    LiveEvalRow,
    build_live_evaluation,
    match_expense_rule,
    match_purchase_rule,
)

_SKIP_STATUSES = frozenset(
    {
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)
_DEFAULT_LIMIT = 50


def _resolve_config(
    org_id: int,
    config_override: dict | RuleBookConfigPayload | None,
) -> RuleBookConfigPayload:
    if config_override is None:
        raw = load_rule_book_config_dict(org_id)
        return validate_rule_book_config_payload(raw)
    if isinstance(config_override, RuleBookConfigPayload):
        return config_override
    return validate_rule_book_config_payload(config_override)


def invoice_to_eval_document(inv: Invoice) -> EvalDocument:
    lines = tuple(
        (line.description or "").strip()
        for line in inv.line_items
        if (line.description or "").strip()
    )
    invoice_no = inv.invoice_no or ""
    doc_number = invoice_no or f"DOC-{inv.id:04d}"
    primary = inv.account_name or "Suspense Account"
    return EvalDocument(
        id=str(inv.id),
        doc_number=doc_number,
        invoice_no=invoice_no,
        vendor=inv.vendor or "",
        abn=inv.abn,
        po=inv.po_reference,
        primary_account=primary,
        lines=lines,
        email_from=inv.email_sender,
        capture_channel=infer_capture_channel(inv.email_sender),
    )


def sample_eval_documents() -> list[EvalDocument]:
    """Fallback when the org has no invoices (demo parity with Rules UI samples)."""
    return [
        EvalDocument(
            id="INV-001",
            doc_number="DOC-2026-0001",
            invoice_no="AWS-AU-204815",
            vendor="Amazon Web Services",
            abn="63 110 305 305",
            address="Level 37, 2-26 Park Street, Sydney NSW 2000",
            po="PO-CLOUD-2026-001",
            primary_account="Cloud Hosting Expense",
            lines=("EC2 Compute - May 2026", "S3 Storage & Data Transfer"),
        ),
        EvalDocument(
            id="INV-002",
            doc_number="DOC-2026-0002",
            invoice_no="SYSCO-INV-88210",
            vendor="Sysco Australia",
            abn="11223344556",
            address="100 Salmon Street, Port Melbourne VIC 3207",
            po="PO-BEV-2026-014",
            primary_account="Raw Materials",
            lines=("Beverage wholesale delivery",),
        ),
        EvalDocument(
            id="INV-003",
            doc_number="DOC-2026-0003",
            invoice_no="ATL-2026-55721",
            vendor="Atlassian Pty Ltd",
            abn="53102443916",
            primary_account="Software Subscription Expense",
            lines=("Jira Cloud subscription",),
        ),
        EvalDocument(
            id="INV-004",
            doc_number="DOC-2026-0004",
            invoice_no="GOOG-AU-99102",
            vendor="Google Australia Pty Ltd",
            po="PO-MKT-2026-014",
            primary_account="Marketing Expense",
            lines=("Google Ads campaign spend",),
        ),
        EvalDocument(
            id="INV-005",
            doc_number="DOC-2026-0005",
            invoice_no="UNKNOWN-001",
            vendor="Sydney Office Florals",
            primary_account="Suspense Account",
            lines=("Office flowers",),
        ),
    ]


def _resolve_ledger(row: LiveEvalRow, config: RuleBookConfigPayload) -> str | None:
    if not row.category_rule:
        return None
    if row.category_rule.kind == "Purchase":
        rule = match_purchase_rule(row.doc, config.purchase_rules)
    else:
        rule = match_expense_rule(row.doc, config.expense_rules)
    return rule.post_to.ledger if rule else None


def serialize_eval_row(row: LiveEvalRow, config: RuleBookConfigPayload) -> dict:
    email_rule = None
    if row.email_rule:
        email_rule = {"id": row.email_rule.id, "name": row.email_rule.name}

    email_rule_disabled = None
    if row.email_rule_disabled:
        email_rule_disabled = {
            "id": row.email_rule_disabled.id,
            "name": row.email_rule_disabled.name,
        }

    vendor_match = None
    if row.vendor.vendor:
        vendor_match = {
            "vendor_id": row.vendor.vendor.id,
            "vendor_name": row.vendor.vendor.name,
            "confidence": row.vendor.confidence,
        }

    category_rule = None
    ledger = row.doc.primary_account
    if row.category_rule:
        category_rule = {
            "label": row.category_rule.label,
            "kind": row.category_rule.kind,
        }
        ledger = _resolve_ledger(row, config) or ledger

    return {
        "document": {
            "id": row.doc.id,
            "doc_number": row.doc.doc_number,
            "invoice_no": row.doc.invoice_no,
            "vendor": row.doc.vendor,
            "primary_account": ledger,
        },
        "email_rule": email_rule,
        "email_rule_disabled": email_rule_disabled,
        "vendor_match": vendor_match,
        "category_rule": category_rule,
        "auto_coded": row.matched and row.category_rule is not None,
    }


async def evaluate_rule_book(
    session: AsyncSession,
    *,
    org_id: int,
    config_override: dict | RuleBookConfigPayload | None = None,
    invoice_ids: list[int] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict:
    config = _resolve_config(org_id, config_override)
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(
            Invoice.org_id == org_id,
            Invoice.status.not_in(_SKIP_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    if invoice_ids:
        stmt = stmt.where(Invoice.id.in_(invoice_ids))
    stmt = stmt.limit(limit if not invoice_ids else max(len(invoice_ids), limit))

    invoices = (await session.execute(stmt)).scalars().all()
    source = "invoices"
    if invoices:
        docs = [invoice_to_eval_document(inv) for inv in invoices]
    else:
        source = "sample"
        docs = sample_eval_documents()

    rows = build_live_evaluation(docs, config)
    return {
        "source": source,
        "rows": [serialize_eval_row(row, config) for row in rows],
    }
