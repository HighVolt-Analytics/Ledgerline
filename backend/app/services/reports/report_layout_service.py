"""Personal named column layouts for catalog reports."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report_column_layout import ReportColumnLayout
from app.schemas.report_catalog import (
    ReportColumnConfig,
    ReportColumnLayoutItem,
    ReportPreview,
    ReportPreviewRow,
)
from app.services.reports.report_catalog import get_report_or_raise


class UnknownLayoutId(LookupError):
    """Raised when a layout is missing for this user/tenant/report."""


class DuplicateLayoutName(ValueError):
    """Raised when a layout name already exists for this user and report."""


def apply_column_layout(preview: ReportPreview, keys: list[str]) -> ReportPreview:
    """Return a copy of preview with columns/cells permuted to `keys`.

    Stale keys are dropped. Unknown live columns not listed stay hidden.
    Empty intersection falls back to the original preview (all columns).
    """
    live = list(preview.columns)
    index_by_name = {name: idx for idx, name in enumerate(live)}
    indices: list[int] = []
    seen: set[str] = set()
    for key in keys:
        token = (key or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        idx = index_by_name.get(token)
        if idx is not None:
            indices.append(idx)
    if not indices:
        return preview
    columns = [live[idx] for idx in indices]
    rows = [
        ReportPreviewRow(
            cells=[row.cells[idx] if idx < len(row.cells) else "" for idx in indices],
            emphasize=row.emphasize,
        )
        for row in preview.rows
    ]
    compare = None
    if preview.compare_columns:
        kept = [name for name in preview.compare_columns if name in columns]
        compare = kept or None
    return preview.model_copy(
        update={"columns": columns, "rows": rows, "compare_columns": compare}
    )


def _item(row: ReportColumnLayout) -> ReportColumnLayoutItem:
    return ReportColumnLayoutItem(
        id=row.id,
        report_id=row.report_id,
        name=row.name,
        column_config=ReportColumnConfig.model_validate(row.column_config),
        is_default=bool(row.is_default),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_owned(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    layout_id: int,
) -> ReportColumnLayout:
    row = (
        await db.execute(
            select(ReportColumnLayout).where(
                ReportColumnLayout.tenant_id == tenant_id,
                ReportColumnLayout.user_id == user_id,
                ReportColumnLayout.report_id == report_id,
                ReportColumnLayout.id == layout_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise UnknownLayoutId(f"Unknown layout: {layout_id}")
    return row


async def _assign_default(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    layout_id: int,
) -> None:
    """One statement: this layout true, every other layout for the user+report false."""
    await db.execute(
        update(ReportColumnLayout)
        .where(
            ReportColumnLayout.tenant_id == tenant_id,
            ReportColumnLayout.user_id == user_id,
            ReportColumnLayout.report_id == report_id,
        )
        .values(
            is_default=case(
                (ReportColumnLayout.id == layout_id, True),
                else_=False,
            ),
            updated_at=datetime.now(timezone.utc),
        )
    )


async def _name_taken(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    name: str,
    *,
    except_id: int | None = None,
) -> bool:
    stmt = select(ReportColumnLayout.id).where(
        ReportColumnLayout.tenant_id == tenant_id,
        ReportColumnLayout.user_id == user_id,
        ReportColumnLayout.report_id == report_id,
        ReportColumnLayout.name == name,
    )
    if except_id is not None:
        stmt = stmt.where(ReportColumnLayout.id != except_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def list_layouts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
) -> list[ReportColumnLayoutItem]:
    get_report_or_raise(report_id)
    rows = (
        await db.execute(
            select(ReportColumnLayout)
            .where(
                ReportColumnLayout.tenant_id == tenant_id,
                ReportColumnLayout.user_id == user_id,
                ReportColumnLayout.report_id == report_id,
            )
            .order_by(ReportColumnLayout.name, ReportColumnLayout.id)
        )
    ).scalars().all()
    return [_item(row) for row in rows]


async def create_layout(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    *,
    name: str,
    column_config: ReportColumnConfig,
    is_default: bool = False,
) -> ReportColumnLayoutItem:
    get_report_or_raise(report_id)
    if await _name_taken(db, tenant_id, user_id, report_id, name):
        raise DuplicateLayoutName(f"Layout name already exists: {name}")
    row = ReportColumnLayout(
        tenant_id=tenant_id,
        user_id=user_id,
        report_id=report_id,
        name=name,
        column_config=column_config.model_dump(),
        is_default=False,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateLayoutName(f"Layout name already exists: {name}") from exc
    if is_default:
        await _assign_default(db, tenant_id, user_id, report_id, row.id)
    await db.refresh(row)
    return _item(row)


async def update_layout(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    layout_id: int,
    *,
    name: str | None = None,
    column_config: ReportColumnConfig | None = None,
) -> ReportColumnLayoutItem:
    get_report_or_raise(report_id)
    row = await _get_owned(db, tenant_id, user_id, report_id, layout_id)
    if name is not None:
        if await _name_taken(
            db, tenant_id, user_id, report_id, name, except_id=layout_id
        ):
            raise DuplicateLayoutName(f"Layout name already exists: {name}")
        row.name = name
    if column_config is not None:
        row.column_config = column_config.model_dump()
    row.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateLayoutName(f"Layout name already exists: {name}") from exc
    await db.refresh(row)
    return _item(row)


async def set_default_layout(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    layout_id: int,
) -> ReportColumnLayoutItem:
    get_report_or_raise(report_id)
    row = await _get_owned(db, tenant_id, user_id, report_id, layout_id)
    await _assign_default(db, tenant_id, user_id, report_id, row.id)
    await db.refresh(row)
    return _item(row)


async def delete_layout(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    layout_id: int,
) -> None:
    get_report_or_raise(report_id)
    row = await _get_owned(db, tenant_id, user_id, report_id, layout_id)
    await db.delete(row)
    await db.flush()


async def load_owned_layout(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_id: str,
    layout_id: int,
) -> ReportColumnLayoutItem:
    get_report_or_raise(report_id)
    row = await _get_owned(db, tenant_id, user_id, report_id, layout_id)
    return _item(row)
