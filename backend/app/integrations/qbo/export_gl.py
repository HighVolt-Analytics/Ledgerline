"""Resolve QBO Bill expense lines: allotted subaccounts, remainder on parent."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.accounts import (
    children_of,
    is_top_level_qbo_account,
    list_active_qbo_accounts,
)
from app.integrations.qbo.store import require_qbo_ready
from app.models.line_item import LineItem
from app.models.qbo_account import QboAccount
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MONEY = Decimal("0.01")
_KIND_SUB = "sub"
_KIND_PARENT = "parent"


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_EVEN)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _line_net_amount(item: Any) -> Decimal | None:
    amount = _decimal(getattr(item, "amount", None))
    if amount is None:
        return None
    quantized = _quantize(amount)
    if quantized == 0:
        return None
    return quantized


def _header_net_amount(invoice: Any) -> Decimal | None:
    subtotal = _decimal(getattr(invoice, "subtotal", None))
    if subtotal is not None:
        quantized = _quantize(subtotal)
        return quantized if quantized != 0 else None
    total = _decimal(getattr(invoice, "total", None))
    gst = _decimal(getattr(invoice, "gst", None)) or Decimal("0")
    if total is None:
        return None
    net = _quantize(total - gst)
    return net if net != 0 else None


def find_parent_qbo_account(
    rows: list[QboAccount],
    *,
    name: str,
    code: str | None = None,
) -> QboAccount | None:
    """Match the document-type Post to ledger to a top-level QBO account. No create."""
    tops = [row for row in rows if is_top_level_qbo_account(row)]
    code_key = (code or "").strip().upper()
    if code_key:
        for row in tops:
            if (row.acct_num or "").strip().upper() == code_key:
                return row
    wanted = _norm(name)
    if not wanted:
        return None
    for row in tops:
        if _norm(row.name) == wanted:
            return row
    for row in tops:
        if _norm(row.fully_qualified_name) == wanted:
            return row
    return None


def find_child_qbo_account(
    parent: QboAccount | None,
    rows: list[QboAccount],
    sub_ledger: str | None,
) -> QboAccount | None:
    """Match a line sub-ledger to a child of the parent. Unmatched → None (remainder)."""
    if parent is None:
        return None
    wanted = _norm(sub_ledger)
    if not wanted or wanted == _norm(parent.name):
        return None
    for child in children_of(parent.qbo_account_id, rows):
        if _norm(child.name) == wanted:
            return child
        leaf = ((child.fully_qualified_name or "").rsplit(":", 1)[-1]).strip()
        if _norm(leaf) == wanted:
            return child
        if (child.acct_num or "").strip().upper() == (sub_ledger or "").strip().upper():
            return child
    return None


def _posting_dict(row: QboAccount, amount: Decimal, kind: str) -> dict[str, Any]:
    return {
        "qbo_account_id": row.qbo_account_id,
        "name": row.name,
        "amount": str(_quantize(amount)),
        "kind": kind,
    }


def split_qbo_gl_postings(
    *,
    parent: QboAccount | None,
    accounts: list[QboAccount],
    line_items: list[Any],
    header_amount: Decimal | None,
) -> list[dict[str, Any]]:
    """Allotted lines → subaccounts; unallotted totals → one parent line. No double count."""
    sub_totals: dict[str, Decimal] = {}
    sub_order: list[str] = []
    remainder = Decimal("0.00")
    used_lines = False

    for item in line_items:
        amount = _line_net_amount(item)
        if amount is None:
            continue
        used_lines = True
        child = find_child_qbo_account(
            parent,
            accounts,
            getattr(item, "sub_ledger", None),
        )
        if child is None:
            remainder += amount
            continue
        key = child.qbo_account_id
        if key not in sub_totals:
            sub_order.append(key)
            sub_totals[key] = Decimal("0.00")
        sub_totals[key] += amount

    if not used_lines and header_amount is not None:
        remainder = header_amount

    by_id = {row.qbo_account_id: row for row in accounts}
    lines: list[dict[str, Any]] = []
    for account_id in sub_order:
        row = by_id.get(account_id)
        amount = _quantize(sub_totals[account_id])
        if row is None or amount == 0:
            continue
        lines.append(_posting_dict(row, amount, _KIND_SUB))

    remainder = _quantize(remainder)
    if remainder != 0 and parent is not None:
        lines.append(_posting_dict(parent, remainder, _KIND_PARENT))
    return lines


async def _load_line_items(db: AsyncSession, invoice: Any) -> list[Any]:
    try:
        state = sa_inspect(invoice)
        unloaded = getattr(state, "unloaded", None) or set()
        if "line_items" not in unloaded:
            cached = invoice.__dict__.get("line_items")
            if cached is not None:
                return list(cached)
    except Exception:
        cached = getattr(invoice, "line_items", None)
        if cached is not None:
            return list(cached)
    invoice_id = getattr(invoice, "id", None)
    if not invoice_id:
        return []
    rows = (
        await db.execute(
            select(LineItem)
            .where(LineItem.invoice_id == invoice_id)
            .order_by(LineItem.id)
        )
    ).scalars().all()
    return list(rows)


async def resolve_invoice_qbo_gl_lines(
    db: AsyncSession,
    invoice: Any,
) -> dict[str, Any] | None:
    """Build Bill GL lines from Post to + line sub-ledgers. Never creates accounts."""
    tenant_id = invoice.tenant_id
    _, realm_id = await require_qbo_ready(db, tenant_id)
    accounts = await list_active_qbo_accounts(db, tenant_id, realm_id)

    parent_name = (getattr(invoice, "account_name", None) or "").strip()
    try:
        from app.services.invoice.line_item_gl_service import resolve_parent_ledger
        from app.services.rule_book.rule_book_mapper import load_classification_config

        config = await load_classification_config(db, tenant_id)
        parent_name = resolve_parent_ledger(invoice, config) or parent_name
    except Exception:
        logger.warning(
            "qbo_export_gl_parent_resolve_failed",
            invoice_id=getattr(invoice, "id", None),
            exc_info=True,
        )

    parent = find_parent_qbo_account(
        accounts,
        name=parent_name,
        code=getattr(invoice, "account_code", None),
    )
    line_items = await _load_line_items(db, invoice)
    lines = split_qbo_gl_postings(
        parent=parent,
        accounts=accounts,
        line_items=line_items,
        header_amount=_header_net_amount(invoice),
    )
    if not lines:
        return None
    return {
        "parent_account_id": parent.qbo_account_id if parent is not None else None,
        "parent_name": parent.name if parent is not None else parent_name or None,
        "lines": lines,
    }
