"""Durable LedgerLink ↔ Xero entity mapping CRUD and completeness checks."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_entity_mapping import (
    MAPPING_GL_ACCOUNT,
    MAPPING_SUPPLIER,
    MAPPING_TAX,
    MAPPING_TRACKING,
    PROVIDER_XERO,
    AccountingEntityMapping,
)
from app.models.xero_account import XeroAccount
from app.models.xero_contact import XeroContact
from app.models.xero_tax_rate import XeroTaxRate
from app.models.xero_tracking_category import XeroTrackingCategory


class MappingServiceError(ValueError):
    def __init__(self, message: str, *, code: str = "mapping_invalid") -> None:
        super().__init__(message)
        self.code = code


async def list_mappings(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mapping_type: str | None = None,
) -> list[AccountingEntityMapping]:
    stmt = select(AccountingEntityMapping).where(
        AccountingEntityMapping.tenant_id == tenant_id,
        AccountingEntityMapping.provider == PROVIDER_XERO,
    )
    if mapping_type:
        stmt = stmt.where(AccountingEntityMapping.mapping_type == mapping_type)
    stmt = stmt.order_by(
        AccountingEntityMapping.mapping_type,
        AccountingEntityMapping.source_key,
    )
    return list((await db.execute(stmt)).scalars().all())


def mapping_to_dict(row: AccountingEntityMapping) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "mapping_type": row.mapping_type,
        "source_key": row.source_key,
        "source_label": row.source_label,
        "external_id": row.external_id,
        "external_code": row.external_code,
        "external_name": row.external_name,
        "external_option_id": row.external_option_id,
        "is_active": row.is_active,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def upsert_mapping(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mapping_type: str,
    source_key: str,
    user_id: int | None,
    source_label: str | None = None,
    external_id: str | None = None,
    external_code: str | None = None,
    external_name: str | None = None,
    external_option_id: str | None = None,
    is_active: bool = True,
    xero_tenant_id: str | None = None,
) -> AccountingEntityMapping:
    mapping_type = mapping_type.strip()
    source_key = source_key.strip()
    if mapping_type not in {
        MAPPING_GL_ACCOUNT,
        MAPPING_TAX,
        MAPPING_TRACKING,
        MAPPING_SUPPLIER,
    }:
        raise MappingServiceError(f"Unsupported mapping type '{mapping_type}'")
    if not source_key:
        raise MappingServiceError("source_key is required")

    await _validate_against_reference(
        db,
        tenant_id=tenant_id,
        mapping_type=mapping_type,
        external_id=external_id,
        external_code=external_code,
        external_option_id=external_option_id,
        xero_tenant_id=xero_tenant_id,
    )

    row = (
        await db.execute(
            select(AccountingEntityMapping).where(
                AccountingEntityMapping.tenant_id == tenant_id,
                AccountingEntityMapping.provider == PROVIDER_XERO,
                AccountingEntityMapping.mapping_type == mapping_type,
                AccountingEntityMapping.source_key == source_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AccountingEntityMapping(
            tenant_id=tenant_id,
            provider=PROVIDER_XERO,
            mapping_type=mapping_type,
            source_key=source_key,
            created_by=user_id,
        )
        db.add(row)

    row.source_label = source_label
    row.external_id = (external_id or "").strip() or None
    row.external_code = (external_code or "").strip() or None
    row.external_name = (external_name or "").strip() or None
    row.external_option_id = (external_option_id or "").strip() or None
    row.is_active = is_active
    row.updated_by = user_id
    await db.flush()
    return row


async def get_mapping(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mapping_type: str,
    source_key: str,
) -> AccountingEntityMapping | None:
    return (
        await db.execute(
            select(AccountingEntityMapping).where(
                AccountingEntityMapping.tenant_id == tenant_id,
                AccountingEntityMapping.provider == PROVIDER_XERO,
                AccountingEntityMapping.mapping_type == mapping_type,
                AccountingEntityMapping.source_key == source_key,
                AccountingEntityMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _validate_against_reference(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mapping_type: str,
    external_id: str | None,
    external_code: str | None,
    external_option_id: str | None,
    xero_tenant_id: str | None,
) -> None:
    if mapping_type == MAPPING_GL_ACCOUNT:
        code = (external_code or "").strip()
        if not code:
            raise MappingServiceError("external_code (Xero AccountCode) is required")
        stmt = select(XeroAccount).where(
            XeroAccount.tenant_id == tenant_id,
            XeroAccount.code == code,
            XeroAccount.sync_status == "active",
        )
        if xero_tenant_id:
            stmt = stmt.where(XeroAccount.xero_tenant_id == xero_tenant_id)
        account = (await db.execute(stmt)).scalars().first()
        if account is None:
            raise MappingServiceError(
                f"Xero account code '{code}' is not in active reference data",
                code="inactive_account_mapping",
            )
        if (account.status or "").upper() == "ARCHIVED":
            raise MappingServiceError(
                f"Xero account code '{code}' is archived",
                code="inactive_account_mapping",
            )
    elif mapping_type == MAPPING_TAX:
        tax_type = (external_code or external_id or "").strip()
        if not tax_type:
            raise MappingServiceError("external_code (Xero TaxType) is required")
        stmt = select(XeroTaxRate).where(
            XeroTaxRate.tenant_id == tenant_id,
            XeroTaxRate.tax_type == tax_type,
            XeroTaxRate.sync_status == "active",
        )
        if xero_tenant_id:
            stmt = stmt.where(XeroTaxRate.xero_tenant_id == xero_tenant_id)
        row = (await db.execute(stmt)).scalars().first()
        if row is None:
            raise MappingServiceError(
                f"Xero tax type '{tax_type}' is not in active reference data",
                code="inactive_tax_mapping",
            )
    elif mapping_type == MAPPING_SUPPLIER:
        contact_id = (external_id or "").strip()
        if not contact_id:
            raise MappingServiceError("external_id (Xero ContactID) is required")
        stmt = select(XeroContact).where(
            XeroContact.tenant_id == tenant_id,
            XeroContact.xero_contact_id == contact_id,
            XeroContact.sync_status == "active",
        )
        if xero_tenant_id:
            stmt = stmt.where(XeroContact.xero_tenant_id == xero_tenant_id)
        row = (await db.execute(stmt)).scalars().first()
        if row is None:
            raise MappingServiceError(
                f"Xero contact '{contact_id}' is not in active reference data",
                code="stale_contact_mapping",
            )
    elif mapping_type == MAPPING_TRACKING:
        option_id = (external_option_id or external_id or "").strip()
        category_id = (external_id or "").strip()
        if not option_id:
            raise MappingServiceError("external_option_id is required for tracking mapping")
        stmt = select(XeroTrackingCategory).where(
            XeroTrackingCategory.tenant_id == tenant_id,
            XeroTrackingCategory.option_external_id == option_id,
            XeroTrackingCategory.sync_status == "active",
            XeroTrackingCategory.is_active.is_(True),
        )
        if category_id:
            stmt = stmt.where(
                XeroTrackingCategory.xero_tracking_category_id == category_id
            )
        if xero_tenant_id:
            stmt = stmt.where(XeroTrackingCategory.xero_tenant_id == xero_tenant_id)
        row = (await db.execute(stmt)).scalars().first()
        if row is None:
            raise MappingServiceError(
                "Tracking option is not in active Xero reference data",
                code="tracking_option_missing",
            )
