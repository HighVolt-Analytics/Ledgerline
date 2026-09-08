"""Pull QuickBooks vendors/customers into Pulled contacts, and create vendors."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.client import QboApiClient, QboApiError
from app.integrations.qbo.store import require_qbo_ready
from app.integrations.xero.sync_counts import ContactsSyncResult, EntitySyncCounters, payload_hash
from app.models.qbo_contact import (
    ENTITY_CUSTOMER,
    ENTITY_VENDOR,
    MAPPING_UNMAPPED,
    SOURCE_SYSTEM_QBO,
    QboContact,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"
_PAGE_SIZE = 1000


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _nested_str(payload: dict[str, Any], *keys: str) -> str | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    text = str(current or "").strip()
    return text[:255] if text else None


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())[:255]


def _fields_from_entity(entity: dict[str, Any], *, entity_type: str) -> dict[str, Any]:
    name = (
        str(entity.get("DisplayName") or entity.get("CompanyName") or entity.get("FullyQualifiedName") or "")
        .strip()[:255]
        or None
    )
    return {
        "name": name,
        "first_name": str(entity.get("GivenName") or "")[:128] or None,
        "last_name": str(entity.get("FamilyName") or "")[:128] or None,
        "email_address": _nested_str(entity, "PrimaryEmailAddr", "Address"),
        "phone": _nested_str(entity, "PrimaryPhone", "FreeFormNumber"),
        "tax_number": str(entity.get("TaxIdentifier") or "")[:64] or None,
        "is_supplier": entity_type == ENTITY_VENDOR,
        "is_customer": entity_type == ENTITY_CUSTOMER,
        "active": bool(entity.get("Active", True)),
    }


async def _query_all(
    client: QboApiClient, entity_name: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 1
    while True:
        statement = (
            f"SELECT * FROM {entity_name} STARTPOSITION {start} MAXRESULTS {_PAGE_SIZE}"
        )
        payload = await client.query(statement)
        query = payload.get("QueryResponse") or {}
        batch = _as_list(query.get(entity_name))
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


async def _upsert_entity(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    integration_id: int,
    realm_id: str,
    entity_type: str,
    entity: dict[str, Any],
    counters: EntitySyncCounters,
    now: datetime,
    seen: set[tuple[str, str]],
) -> None:
    entity_id = str(entity.get("Id") or "").strip()
    if not entity_id:
        return
    counters.fetched += 1
    seen.add((entity_type, entity_id))
    hash_value = payload_hash(entity)
    existing = (
        await db.execute(
            select(QboContact).where(
                QboContact.tenant_id == tenant_id,
                QboContact.realm_id == realm_id,
                QboContact.entity_type == entity_type,
                QboContact.qbo_entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    fields = _fields_from_entity(entity, entity_type=entity_type)
    sync_status = _SYNC_ACTIVE if fields["active"] else _SYNC_INACTIVE
    if existing is None:
        db.add(
            QboContact(
                tenant_id=tenant_id,
                accounting_integration_id=integration_id,
                realm_id=realm_id,
                entity_type=entity_type,
                qbo_entity_id=entity_id,
                mapping_status=MAPPING_UNMAPPED,
                source_system=SOURCE_SYSTEM_QBO,
                sync_status=sync_status,
                payload_hash=hash_value,
                raw_payload_json=json.dumps(entity, default=str),
                last_seen_at=now,
                last_synced_at=now,
                **fields,
            )
        )
        counters.created += 1
        return
    if existing.payload_hash == hash_value and existing.sync_status == sync_status:
        existing.last_seen_at = now
        existing.last_synced_at = now
        counters.unchanged += 1
        return
    for key, value in fields.items():
        setattr(existing, key, value)
    existing.sync_status = sync_status
    existing.payload_hash = hash_value
    existing.raw_payload_json = json.dumps(entity, default=str)
    existing.last_seen_at = now
    existing.last_synced_at = now
    counters.updated += 1


async def sync_contacts(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    result = ContactsSyncResult()
    now = datetime.now(timezone.utc)
    seen: set[tuple[str, str]] = set()

    for entity_name, entity_type in (("Vendor", ENTITY_VENDOR), ("Customer", ENTITY_CUSTOMER)):
        try:
            entities = await _query_all(client, entity_name)
        except QboApiError:
            raise
        except Exception as exc:
            logger.warning(
                "qbo_contact_query_failed",
                tenant_id=str(tenant_id),
                entity=entity_name,
                error=str(exc),
            )
            raise
        for entity in entities:
            try:
                await _upsert_entity(
                    db,
                    tenant_id=tenant_id,
                    integration_id=integration.id,
                    realm_id=realm_id,
                    entity_type=entity_type,
                    entity=entity,
                    counters=result.contacts,
                    now=now,
                    seen=seen,
                )
            except Exception as exc:
                result.contacts.failed += 1
                logger.warning(
                    "qbo_contact_upsert_failed",
                    tenant_id=str(tenant_id),
                    entity_type=entity_type,
                    error=str(exc),
                )

    for row in (
        await db.execute(
            select(QboContact).where(
                QboContact.tenant_id == tenant_id,
                QboContact.realm_id == realm_id,
                QboContact.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if (row.entity_type, row.qbo_entity_id) not in seen:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            result.contacts.deactivated += 1

    integration.last_successful_sync_at = now
    await db.flush()
    payload = result.to_response()
    payload["committed"] = False
    return payload


def serialize_contact(row: QboContact) -> dict[str, Any]:
    return {
        "id": row.id,
        "qbo_entity_id": row.qbo_entity_id,
        "entity_type": row.entity_type,
        "realm_id": row.realm_id,
        "name": row.name,
        "email_address": row.email_address,
        "phone": row.phone,
        "is_supplier": row.is_supplier,
        "is_customer": row.is_customer,
        "mapping_status": row.mapping_status,
        "sync_status": row.sync_status,
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
        "xero_contact_id": f"{row.entity_type}:{row.qbo_entity_id}",
    }


async def list_contacts(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _, realm_id = await require_qbo_ready(db, tenant_id)
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    stmt = select(QboContact).where(
        QboContact.tenant_id == tenant_id,
        QboContact.realm_id == realm_id,
        QboContact.sync_status == _SYNC_ACTIVE,
    )
    count_stmt = select(func.count()).select_from(QboContact).where(
        QboContact.tenant_id == tenant_id,
        QboContact.realm_id == realm_id,
        QboContact.sync_status == _SYNC_ACTIVE,
    )
    if search:
        term = search.strip().lower()
        like = f"%{term}%"
        filt = or_(
            func.lower(QboContact.name).like(like),
            func.lower(QboContact.email_address).like(like),
            func.lower(QboContact.qbo_entity_id).like(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(QboContact.name.asc(), QboContact.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [serialize_contact(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def create_contact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    display_name: str,
    entity_type: str = ENTITY_VENDOR,
    given_name: str | None = None,
    family_name: str | None = None,
    company_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    tax_identifier: str | None = None,
) -> dict[str, Any]:
    legal_name = display_name.strip()
    if not legal_name:
        raise ValueError("name_required")
    kind = entity_type.strip().lower()
    if kind not in {ENTITY_VENDOR, ENTITY_CUSTOMER}:
        raise ValueError("type_required")
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    wanted = _normalize_name(legal_name)
    existing = (
        await db.execute(
            select(QboContact).where(
                QboContact.tenant_id == tenant_id,
                QboContact.realm_id == realm_id,
                QboContact.entity_type == kind,
                QboContact.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars().all()
    matches = [row for row in existing if _normalize_name(row.name or "") == wanted]
    if len(matches) == 1:
        return {
            "created": False,
            "reused": True,
            "contact_id": matches[0].qbo_entity_id,
            "name": matches[0].name,
            "entity_type": kind,
        }
    if len(matches) > 1:
        raise ValueError("ambiguous_vendor_match")

    body: dict[str, Any] = {"DisplayName": legal_name}
    if company_name and company_name.strip():
        body["CompanyName"] = company_name.strip()[:100]
    if given_name and given_name.strip():
        body["GivenName"] = given_name.strip()[:25]
    if family_name and family_name.strip():
        body["FamilyName"] = family_name.strip()[:25]
    if email and email.strip():
        body["PrimaryEmailAddr"] = {"Address": email.strip()[:100]}
    if phone and phone.strip():
        body["PrimaryPhone"] = {"FreeFormNumber": phone.strip()[:30]}
    if tax_identifier and tax_identifier.strip():
        body["TaxIdentifier"] = tax_identifier.strip()[:20]

    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    path = "vendor" if kind == ENTITY_VENDOR else "customer"
    payload = await client.post_entity(path, body)
    created = payload.get("Vendor") if kind == ENTITY_VENDOR else payload.get("Customer")
    if not isinstance(created, dict):
        created = payload if isinstance(payload, dict) else {}
    entity_id = str((created or {}).get("Id") or "").strip()
    if not entity_id:
        raise ValueError("QuickBooks returned no contact")

    now = datetime.now(timezone.utc)
    fields = _fields_from_entity(created, entity_type=kind)
    db.add(
        QboContact(
            tenant_id=tenant_id,
            accounting_integration_id=integration.id,
            realm_id=realm_id,
            entity_type=kind,
            qbo_entity_id=entity_id,
            mapping_status=MAPPING_UNMAPPED,
            source_system=SOURCE_SYSTEM_QBO,
            sync_status=_SYNC_ACTIVE,
            payload_hash=payload_hash(created),
            raw_payload_json=json.dumps(created, default=str),
            last_seen_at=now,
            last_synced_at=now,
            **fields,
        )
    )
    await db.flush()
    return {
        "created": True,
        "reused": False,
        "contact_id": entity_id,
        "name": fields.get("name") or legal_name,
        "entity_type": kind,
    }


async def create_vendor(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    display_name: str,
) -> dict[str, Any]:
    return await create_contact(
        db, tenant_id=tenant_id, display_name=display_name, entity_type=ENTITY_VENDOR
    )


async def create_customer(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    display_name: str,
) -> dict[str, Any]:
    return await create_contact(
        db, tenant_id=tenant_id, display_name=display_name, entity_type=ENTITY_CUSTOMER
    )


async def ensure_invoice_qbo_contact(
    db: AsyncSession,
    invoice: Any,
) -> dict[str, Any] | None:
    """Match or create a QBO Vendor/Customer from the extracted invoice name.

    Entity type comes from the document type Counterparty type field (vendor vs
    customer). No-op when QuickBooks is disconnected or the name is blank.
    Never raises — processing must continue.
    """
    legal_name = (getattr(invoice, "vendor", None) or "").strip()
    if not legal_name:
        return None
    tenant_id = invoice.tenant_id
    try:
        await require_qbo_ready(db, tenant_id)
    except Exception:
        return None

    entity_type = ENTITY_VENDOR
    try:
        from app.schemas.document_type import resolved_counterparty_type
        from app.services.master_data.vendor_registration_policy import (
            resolve_document_type_definition,
        )
        from app.services.rule_book.rule_book_mapper import load_classification_config

        config = await load_classification_config(db, tenant_id)
        definition = resolve_document_type_definition(
            getattr(invoice, "document_type_code", None),
            document_types=config.document_types,
        )
        entity_type = resolved_counterparty_type(
            definition,
            route_target=getattr(invoice, "route_target", None),
        )
    except Exception:
        logger.warning(
            "qbo_invoice_contact_type_resolve_failed",
            invoice_id=getattr(invoice, "id", None),
            tenant_id=str(tenant_id),
            exc_info=True,
        )

    try:
        return await create_contact(
            db,
            tenant_id=tenant_id,
            display_name=legal_name,
            entity_type=entity_type,
            email=getattr(invoice, "email_sender", None),
            tax_identifier=getattr(invoice, "abn", None),
        )
    except (QboApiError, ValueError) as exc:
        logger.warning(
            "qbo_invoice_contact_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            tenant_id=str(tenant_id),
            entity_type=entity_type,
            error=str(exc),
        )
        return None
    except Exception as exc:
        logger.warning(
            "qbo_invoice_contact_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            tenant_id=str(tenant_id),
            error=str(exc),
        )
        return None
