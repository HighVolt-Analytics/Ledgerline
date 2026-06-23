"""Evaluate rule book against organisation documents."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import EmailCaptureRule, RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.capture_channel import infer_capture_channel
from app.services.document_ref_service import display_document_ref
from app.services.po_reference import effective_po_reference
from app.services.rule_engine import (
    EvalDocument,
    LiveEvalRow,
    build_live_evaluation,
    match_expense_rule,
    match_purchase_rule,
    match_team_expense_rule,
)

_SKIP_STATUSES = frozenset(
    {
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)
_DEFAULT_LIMIT = 50


async def _resolve_config(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config_override: dict | RuleBookConfigPayload | None,
) -> RuleBookConfigPayload:
    if config_override is None:
        from app.services.rule_book_config_io import load_rule_book_config_with_masters

        raw = await load_rule_book_config_with_masters(session, tenant_id)
        return validate_rule_book_config_payload(raw)
    if isinstance(config_override, RuleBookConfigPayload):
        return config_override
    return validate_rule_book_config_payload(config_override)


def invoice_to_eval_document(inv: Invoice) -> EvalDocument:
    state = inspect(inv)
    if "line_items" in state.unloaded:
        lines: tuple[str, ...] = ()
    else:
        lines = tuple(
            (line.description or "").strip()
            for line in inv.line_items
            if (line.description or "").strip()
        )
    invoice_no = (inv.invoice_no or "").strip()
    doc_number = display_document_ref(inv)
    primary = inv.account_name or "Suspense Account"
    doc_type = "invoice"
    if inv.purchase_document_type == "po":
        doc_type = "po"
    elif inv.purchase_document_type == "grn":
        doc_type = "grn"

    return EvalDocument(
        id=str(inv.id),
        doc_number=doc_number,
        invoice_no=invoice_no,
        vendor=inv.vendor or "",
        abn=inv.abn,
        po=effective_po_reference(inv.po_reference),
        primary_account=primary,
        lines=lines,
        document_type=doc_type,
        email_from=inv.email_sender,
        email_subject=inv.email_subject,
        email_attachment_name=inv.email_attachment_name,
        capture_channel=infer_capture_channel(inv.email_sender),
        address=inv.billing_address,
        bank_bsb=inv.bank_bsb,
        bank_account=inv.bank_account,
    )


def sample_eval_documents() -> list[EvalDocument]:
    """No synthetic samples — live eval uses real invoices only."""
    return []


def _legacy_sample_eval_documents() -> list[EvalDocument]:
    """Retained for unit tests only (see tests/fixtures/rule_book_demo.json)."""
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


def _parse_matched_rule_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(item) for item in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _email_capture_rule_from_ids(
    matched_rule_ids: str | None,
    rules: list[EmailCaptureRule],
) -> EmailCaptureRule | None:
    for token in _parse_matched_rule_ids(matched_rule_ids):
        if not token.startswith("email:"):
            continue
        rule_id = token.split(":", 1)[1]
        for rule in rules:
            if rule.id == rule_id:
                return rule
    return None


def _apply_stored_email_capture(
    rows: list[LiveEvalRow],
    invoices: list[Invoice],
    config: RuleBookConfigPayload,
) -> list[LiveEvalRow]:
    """Live eval replays synthetic emails; show ingest-time capture from matched_rule_ids."""
    if len(rows) != len(invoices):
        return rows
    out: list[LiveEvalRow] = []
    for inv, row in zip(invoices, rows, strict=True):
        if row.email_rule is not None:
            out.append(row)
            continue
        stored = _email_capture_rule_from_ids(inv.matched_rule_ids, config.email_capture_rules)
        if stored is None:
            out.append(row)
            continue
        out.append(
            LiveEvalRow(
                doc=row.doc,
                email_rule=stored,
                email_rule_disabled=None,
                vendor=row.vendor,
                category_rule=row.category_rule,
                category_rule_disabled=row.category_rule_disabled,
                matched=row.matched,
            )
        )
    return out


def _resolve_ledger(row: LiveEvalRow, config: RuleBookConfigPayload) -> str | None:
    if not row.category_rule:
        return None
    if row.category_rule.kind == "Purchase":
        rule = match_purchase_rule(row.doc, config.purchase_rules)
    elif row.category_rule.kind == "Expense":
        rule = match_expense_rule(row.doc, config.expense_rules)
    else:
        rule = match_team_expense_rule(row.doc, config.team_expense_rules)
    return rule.post_to.ledger if rule else None


def _fallback_document_type_code(
    inv: Invoice,
    config: RuleBookConfigPayload,
) -> str | None:
    explicit = (inv.document_type_code or "").strip().upper()
    if explicit:
        return explicit

    purchase_kind = (inv.purchase_document_type or "").strip().lower()
    if purchase_kind in {"po", "grn"}:
        for dt in config.document_types:
            if (dt.purchase_bundle_role or "").strip().lower() == purchase_kind:
                return dt.code
    return None


def serialize_eval_row(
    row: LiveEvalRow,
    config: RuleBookConfigPayload,
    *,
    document_type_code: str | None = None,
) -> dict:
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
    category_rule_disabled = None
    ledger = row.doc.primary_account
    if row.category_rule:
        category_rule = {
            "label": row.category_rule.label,
            "kind": row.category_rule.kind,
        }
        ledger = _resolve_ledger(row, config) or ledger
    elif row.category_rule_disabled:
        category_rule_disabled = {
            "label": row.category_rule_disabled.label,
            "kind": row.category_rule_disabled.kind,
        }

    return {
        "document": {
            "id": row.doc.id,
            "doc_number": row.doc.doc_number,
            "invoice_no": row.doc.invoice_no,
            "vendor": row.doc.vendor,
            "primary_account": ledger,
            "document_type_code": document_type_code,
        },
        "email_rule": email_rule,
        "email_rule_disabled": email_rule_disabled,
        "vendor_match": vendor_match,
        "category_rule": category_rule,
        "category_rule_disabled": category_rule_disabled,
        "auto_coded": row.matched and row.category_rule is not None,
    }


async def evaluate_rule_book(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    config_override: dict | RuleBookConfigPayload | None = None,
    invoice_ids: list[int] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict:
    config = await _resolve_config(session, tenant_id, config_override)
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.not_in(_SKIP_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    if invoice_ids:
        stmt = stmt.where(Invoice.id.in_(invoice_ids))
    stmt = stmt.limit(limit if not invoice_ids else max(len(invoice_ids), limit))

    invoices = (await session.execute(stmt)).scalars().all()
    if invoices:
        source = "invoices"
        docs = [invoice_to_eval_document(inv) for inv in invoices]
    else:
        docs = sample_eval_documents()
        source = "sample" if docs else "invoices"

    mailbox = get_settings().graph_mailbox.strip() or "accounts@acme-hospitality.com.au"
    rows = build_live_evaluation(docs, config, default_mailbox=mailbox)
    if invoices:
        rows = _apply_stored_email_capture(rows, invoices, config)
    doc_type_by_doc_id: dict[str, str | None] = {}
    for inv in invoices:
        doc_type_by_doc_id[str(inv.id)] = _fallback_document_type_code(inv, config)
    return {
        "source": source,
        "rows": [
            serialize_eval_row(
                row,
                config,
                document_type_code=doc_type_by_doc_id.get(str(row.doc.id)),
            )
            for row in rows
        ],
    }
