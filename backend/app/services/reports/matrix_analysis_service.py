"""Aggregate matrix / upload analysis for a scoped document set."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.matrix_analysis import (
    MatrixAnalysisBoardRow,
    MatrixAnalysisFunnelRow,
    MatrixAnalysisIssueRow,
    MatrixAnalysisResponse,
    MatrixAnalysisSummary,
)
from app.schemas.matrix_api import MatrixListRequest
from app.services.approval.approval_board_service import approval_board_column, approval_board_column_expr
from app.services.invoice.invoice_related_query_service import audit_logs_for_invoice_ids
from app.services.invoice.invoice_response_service import invoice_list_load_options
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.invoice.pipeline_stages import MATRIX_STAGES, build_matrix_cells
from app.services.reports.matrix_service import (
    _apply_capture_source,
    _apply_route_target,
    _apply_search,
    _matrix_summary,
    _scoped_invoice_query,
    derive_matrix_flag,
)
from app.services.shared.currency import UNKNOWN_CURRENCY, prefer_currency

_MAX_ANALYSIS_DOCS = 2500

_BOARD_LABELS = {
    "review": "To Review",
    "processing": "Processing",
    "approved": "Approved",
    "rejected": "Rejected",
}

_SETTLED_STAGE_STATES = frozenset({"done", "skipped"})


@dataclass
class _IssueBucket:
    type: str
    flag: str
    items: int = 0
    at_risk_by_currency: dict[str, Decimal] = field(default_factory=dict)


def _currency_code(inv: Invoice) -> str:
    code = prefer_currency(inv.currency)
    return code or UNKNOWN_CURRENCY


def _invoice_amount(inv: Invoice) -> Decimal:
    if inv.total is None:
        return Decimal("0")
    try:
        return Decimal(str(inv.total))
    except Exception:
        return Decimal("0")


def _add_amount(bucket: dict[str, Decimal], currency: str, amount: Decimal) -> None:
    if amount == 0:
        return
    bucket[currency] = bucket.get(currency, Decimal("0")) + amount


def _decimal_map_to_float(bucket: dict[str, Decimal]) -> dict[str, float]:
    return {code: float(amount) for code, amount in sorted(bucket.items()) if amount != 0}


def _issue_label(flag: str, reason: str | None) -> tuple[str, str]:
    token = (reason or "").strip()
    if flag == "Anomaly Detected" and token:
        return token[:120], flag
    return flag, flag


def _issue_severity(flag: str, label: str) -> str:
    if flag in {"Duplicate Suspected", "Quarantined"}:
        return "High"
    lowered = label.lower()
    if "suspense" in lowered or "duplicate" in lowered:
        return "High"
    if flag in {"Awaiting approval", "Awaiting linkage", "Anomaly Detected"}:
        return "Medium"
    return "Low"


def _scope_params(params: MatrixListRequest) -> MatrixListRequest:
    return params.model_copy(update={"approval_board_column": None})


async def _board_rows(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: MatrixListRequest,
) -> list[MatrixAnalysisBoardRow]:
    board_params = _scope_params(params)
    col = approval_board_column_expr()
    currency_expr = func.upper(func.trim(func.coalesce(Invoice.currency, "")))
    stmt = (
        select(
            col.label("board"),
            currency_expr.label("currency"),
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.total), 0),
            func.avg(
                func.extract(
                    "epoch",
                    func.now() - Invoice.created_at,
                )
                / 86_400.0
            ),
        )
        .where(Invoice.tenant_id == tenant_id)
        .group_by(col, currency_expr)
    )
    stmt = _apply_capture_source(stmt, board_params.capture_source)
    stmt = _apply_route_target(stmt, board_params.route_target)
    stmt = _apply_search(stmt, board_params.q)

    rows_by_key: dict[str, MatrixAnalysisBoardRow] = {
        key: MatrixAnalysisBoardRow(
            key=key,
            column=label,
            items=0,
            value_by_currency={},
            avg_wait_days=0,
            flagged=0,
        )
        for key, label in _BOARD_LABELS.items()
    }
    value_by_board: dict[str, dict[str, Decimal]] = defaultdict(dict)
    wait_weight_by_board: dict[str, list[tuple[float, int]]] = defaultdict(list)

    for board, currency, count, value, avg_wait in (await db.execute(stmt)).all():
        key = str(board or "")
        if key not in rows_by_key:
            continue
        row_count = int(count or 0)
        currency_code = prefer_currency(str(currency or "")) or UNKNOWN_CURRENCY
        amount = Decimal(str(value or 0))
        _add_amount(value_by_board[key], currency_code, amount)

        existing = rows_by_key[key]
        rows_by_key[key] = MatrixAnalysisBoardRow(
            key=key,
            column=_BOARD_LABELS[key],
            items=existing.items + row_count,
            value_by_currency={},
            avg_wait_days=existing.avg_wait_days,
            flagged=existing.flagged,
        )
        if avg_wait is not None and row_count > 0:
            wait_weight_by_board[key].append((float(avg_wait), row_count))

    for key, weights in wait_weight_by_board.items():
        total_items = sum(weight for _, weight in weights)
        if total_items <= 0:
            continue
        avg_wait = sum(value * weight for value, weight in weights) / total_items
        row = rows_by_key[key]
        rows_by_key[key] = MatrixAnalysisBoardRow(
            key=row.key,
            column=row.column,
            items=row.items,
            value_by_currency=_decimal_map_to_float(value_by_board[key]),
            avg_wait_days=round(avg_wait, 1),
            flagged=row.flagged,
        )

    for key in rows_by_key:
        if value_by_board.get(key):
            row = rows_by_key[key]
            rows_by_key[key] = MatrixAnalysisBoardRow(
                key=row.key,
                column=row.column,
                items=row.items,
                value_by_currency=_decimal_map_to_float(value_by_board[key]),
                avg_wait_days=row.avg_wait_days,
                flagged=row.flagged,
            )

    list_stmt, _ = _scoped_invoice_query(tenant_id, board_params)
    list_stmt = list_stmt.limit(_MAX_ANALYSIS_DOCS)
    invoices = (await db.execute(list_stmt.options(*invoice_list_load_options()))).scalars().all()
    config = await load_posting_config_for_tenant(db, tenant_id)
    document_types = list(config.document_types or [])
    flagged_by_board: dict[str, int] = defaultdict(int)
    for inv in invoices:
        flag, _ = derive_matrix_flag(inv, document_types=document_types)
        if flag == "Clean":
            continue
        flagged_by_board[approval_board_column(inv)] += 1

    return [
        MatrixAnalysisBoardRow(
            key=key,
            column=rows_by_key[key].column,
            items=rows_by_key[key].items,
            value_by_currency=rows_by_key[key].value_by_currency,
            avg_wait_days=rows_by_key[key].avg_wait_days,
            flagged=int(flagged_by_board.get(key, 0)),
        )
        for key in ("review", "processing", "approved", "rejected")
    ]


def _filter_board_rows(
    rows: list[MatrixAnalysisBoardRow],
    approval_board_column: str | None,
) -> list[MatrixAnalysisBoardRow]:
    valid = {"review", "processing", "approved", "rejected"}
    tokens = [
        part.strip().lower()
        for part in (approval_board_column or "").split(",")
        if part.strip()
    ]
    tokens = [token for token in tokens if token in valid]
    if not tokens:
        return rows
    allowed = set(tokens)
    return [
        row
        if row.key in allowed
        else MatrixAnalysisBoardRow(
            key=row.key,
            column=row.column,
            items=0,
            value_by_currency={},
            avg_wait_days=0,
            flagged=0,
        )
        for row in rows
    ]


def _build_funnel(stage_counts: dict[str, int], base_count: int) -> list[MatrixAnalysisFunnelRow]:
    rows: list[MatrixAnalysisFunnelRow] = []
    prev_count: int | None = None
    for stage in MATRIX_STAGES:
        count = int(stage_counts.get(stage, 0))
        delta = None if prev_count is None else count - prev_count
        pct = 100.0 if base_count <= 0 else min(100.0, (count / base_count) * 100.0)
        rows.append(
            MatrixAnalysisFunnelRow(
                stage=stage,
                count=count,
                delta=delta,
                pct=round(pct, 1),
            )
        )
        prev_count = count
    return rows


async def fetch_matrix_analysis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: MatrixListRequest,
) -> MatrixAnalysisResponse:
    stmt, count_stmt = _scoped_invoice_query(tenant_id, params)
    total = int((await db.execute(count_stmt)).scalar() or 0)
    truncated = total > _MAX_ANALYSIS_DOCS

    stmt = (
        stmt.options(*invoice_list_load_options())
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .limit(_MAX_ANALYSIS_DOCS)
    )
    invoices = (await db.execute(stmt)).scalars().all()
    analyzed_count = len(invoices)

    invoice_ids = [inv.id for inv in invoices]
    audit_by_id = await audit_logs_for_invoice_ids(
        db,
        invoice_ids,
        tenant_id=tenant_id,
        per_invoice_limit=40,
    )
    config = await load_posting_config_for_tenant(db, tenant_id)
    document_types = list(config.document_types or [])

    stage_counts: dict[str, int] = dict.fromkeys(MATRIX_STAGES, 0)
    issue_buckets: dict[str, _IssueBucket] = {}

    for inv in invoices:
        cells = build_matrix_cells(inv, audit_by_id.get(inv.id, []))
        for cell in cells:
            stage = str(cell.get("stage", ""))
            state = str(cell.get("state", ""))
            if stage in stage_counts and state in _SETTLED_STAGE_STATES:
                stage_counts[stage] += 1

        flag, reason = derive_matrix_flag(inv, document_types=document_types)
        if flag == "Clean":
            continue
        label, flag_key = _issue_label(flag, reason)
        bucket = issue_buckets.get(label)
        amount = _invoice_amount(inv)
        currency = _currency_code(inv)
        if bucket is None:
            at_risk = {}
            _add_amount(at_risk, currency, amount)
            issue_buckets[label] = _IssueBucket(
                type=label,
                flag=flag_key,
                items=1,
                at_risk_by_currency=at_risk,
            )
        else:
            _add_amount(bucket.at_risk_by_currency, currency, amount)
            bucket.items += 1

    base_count = max(stage_counts.get("Received", 0), analyzed_count, 1)
    funnel = _build_funnel(stage_counts, base_count)

    exception_mix: list[MatrixAnalysisIssueRow] = []
    for bucket in sorted(
        issue_buckets.values(),
        key=lambda row: (sum(row.at_risk_by_currency.values()), row.items),
        reverse=True,
    ):
        severity = _issue_severity(bucket.flag, bucket.type)
        exception_mix.append(
            MatrixAnalysisIssueRow(
                type=bucket.type,
                items=bucket.items,
                at_risk_by_currency=_decimal_map_to_float(bucket.at_risk_by_currency),
                severity=severity,
                highlight=severity == "High" and bucket.items > 0,
            )
        )

    flagged, duplicates, awaiting, paid = await _matrix_summary(
        db, tenant_id=tenant_id, params=params
    )
    board = _filter_board_rows(
        await _board_rows(db, tenant_id=tenant_id, params=params),
        params.approval_board_column,
    )

    return MatrixAnalysisResponse(
        approval_board=board,
        processing_funnel=funnel,
        exception_mix=exception_mix,
        summary=MatrixAnalysisSummary(
            document_count=total,
            flagged=flagged,
            duplicates=duplicates,
            awaiting=awaiting,
            paid_this_month=paid,
            truncated=truncated,
            analyzed_count=analyzed_count,
        ),
    )
