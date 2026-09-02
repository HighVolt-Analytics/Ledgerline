"""Deterministic supplier contact resolution against local Xero contact cache."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_entity_mapping import MAPPING_SUPPLIER
from app.models.xero_contact import MAPPING_MAPPED, XeroContact
from app.services.integration.accounting_integration_service import require_xero_ready
from app.services.integration.accounting_mapping_service import get_mapping, upsert_mapping
from app.integrations.xero.client import XeroApiClient, XeroApiError


MatchOutcome = Literal["matched", "ambiguous", "none", "mapped"]


@dataclass
class ContactMatch:
    outcome: MatchOutcome
    contact_id: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None


def _normalize_name(name: str) -> str:
    collapsed = re.sub(r"\s+", " ", (name or "").strip().lower())
    return collapsed[:255]


def _normalize_tax(tax_id: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", (tax_id or "").strip()).upper()


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _candidate_dict(row: XeroContact) -> dict[str, Any]:
    return {
        "xero_contact_id": row.xero_contact_id,
        "name": row.name,
        "email_address": row.email_address,
        "tax_number": row.tax_number,
        "is_supplier": row.is_supplier,
        "contact_status": row.contact_status,
    }


async def resolve_supplier_contact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
    supplier_key: str,
    legal_name: str,
    tax_id: str | None = None,
    email: str | None = None,
    existing_contact_id: str | None = None,
) -> ContactMatch:
    """Resolve ContactID without fuzzy matching.

    Order:
    1. Stored organisation-scoped mapping / explicit ContactID
    2. Tax ID exact
    3. Exact normalised legal name
    4. Email exact
    Ambiguous (>1) → HUMAN_REVIEW; none → caller may auto-create on export.
    """
    if existing_contact_id and existing_contact_id.strip():
        row = (
            await db.execute(
                select(XeroContact).where(
                    XeroContact.tenant_id == tenant_id,
                    XeroContact.xero_tenant_id == xero_tenant_id,
                    XeroContact.xero_contact_id == existing_contact_id.strip(),
                    XeroContact.sync_status == "active",
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return ContactMatch(
                outcome="mapped",
                contact_id=row.xero_contact_id,
                candidates=[_candidate_dict(row)],
                reason="existing_contact_id",
            )

    mapped = await get_mapping(
        db,
        tenant_id=tenant_id,
        mapping_type=MAPPING_SUPPLIER,
        source_key=supplier_key,
        xero_tenant_id=xero_tenant_id,
    )
    if mapped and mapped.external_id:
        row = (
            await db.execute(
                select(XeroContact).where(
                    XeroContact.tenant_id == tenant_id,
                    XeroContact.xero_tenant_id == xero_tenant_id,
                    XeroContact.xero_contact_id == mapped.external_id,
                    XeroContact.sync_status == "active",
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return ContactMatch(
                outcome="mapped",
                contact_id=row.xero_contact_id,
                candidates=[_candidate_dict(row)],
                reason="stored_mapping",
            )

    contacts = list(
        (
            await db.execute(
                select(XeroContact).where(
                    XeroContact.tenant_id == tenant_id,
                    XeroContact.xero_tenant_id == xero_tenant_id,
                    XeroContact.sync_status == "active",
                )
            )
        ).scalars().all()
    )

    tax_norm = _normalize_tax(tax_id)
    name_norm = _normalize_name(legal_name)
    email_norm = _normalize_email(email)

    tax_hits = [
        c
        for c in contacts
        if tax_norm and _normalize_tax(c.tax_number) == tax_norm
    ]
    if len(tax_hits) == 1:
        return ContactMatch(
            outcome="matched",
            contact_id=tax_hits[0].xero_contact_id,
            candidates=[_candidate_dict(tax_hits[0])],
            reason="tax_id",
        )
    if len(tax_hits) > 1:
        return ContactMatch(
            outcome="ambiguous",
            candidates=[_candidate_dict(c) for c in tax_hits],
            reason="tax_id",
        )

    name_hits = [
        c for c in contacts if name_norm and _normalize_name(c.name or "") == name_norm
    ]
    if len(name_hits) == 1:
        return ContactMatch(
            outcome="matched",
            contact_id=name_hits[0].xero_contact_id,
            candidates=[_candidate_dict(name_hits[0])],
            reason="legal_name",
        )
    if len(name_hits) > 1:
        return ContactMatch(
            outcome="ambiguous",
            candidates=[_candidate_dict(c) for c in name_hits],
            reason="legal_name",
        )

    email_hits = [
        c
        for c in contacts
        if email_norm and _normalize_email(c.email_address) == email_norm
    ]
    if len(email_hits) == 1:
        return ContactMatch(
            outcome="matched",
            contact_id=email_hits[0].xero_contact_id,
            candidates=[_candidate_dict(email_hits[0])],
            reason="email",
        )
    if len(email_hits) > 1:
        return ContactMatch(
            outcome="ambiguous",
            candidates=[_candidate_dict(c) for c in email_hits],
            reason="email",
        )

    return ContactMatch(outcome="none", reason="no_strong_match")


async def save_supplier_contact_mapping(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    supplier_key: str,
    legal_name: str,
    contact_id: str,
    user_id: int | None,
    xero_tenant_id: str,
) -> None:
    await upsert_mapping(
        db,
        tenant_id=tenant_id,
        mapping_type=MAPPING_SUPPLIER,
        source_key=supplier_key,
        source_label=legal_name,
        external_id=contact_id,
        external_name=legal_name,
        user_id=user_id,
        xero_tenant_id=xero_tenant_id,
    )
    contact = (
        await db.execute(
            select(XeroContact).where(
                XeroContact.tenant_id == tenant_id,
                XeroContact.xero_tenant_id == xero_tenant_id,
                XeroContact.xero_contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if contact is not None:
        contact.mapping_status = MAPPING_MAPPED


async def create_xero_supplier_contact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    supplier_key: str,
    legal_name: str,
    tax_id: str | None = None,
    email: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Create a Xero supplier contact when exact resolution finds no match.

    Idempotent within tenant + Xero organisation: re-resolves first and reuses a
    single exact match. Never called for ambiguous matches.
    """
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)

    existing = await resolve_supplier_contact(
        db,
        tenant_id=tenant_id,
        xero_tenant_id=xero_tenant_id,
        supplier_key=supplier_key,
        legal_name=legal_name,
        tax_id=tax_id,
        email=email,
    )
    if existing.outcome in {"matched", "mapped"} and existing.contact_id:
        await save_supplier_contact_mapping(
            db,
            tenant_id=tenant_id,
            supplier_key=supplier_key,
            legal_name=legal_name,
            contact_id=existing.contact_id,
            user_id=user_id,
            xero_tenant_id=xero_tenant_id,
        )
        return {
            "created": False,
            "reused": True,
            "contact_id": existing.contact_id,
            "reason": existing.reason,
        }
    if existing.outcome == "ambiguous":
        raise ValueError("ambiguous_supplier_match")

    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    body: dict[str, Any] = {
        "Name": legal_name.strip(),
        "IsSupplier": True,
        "IsCustomer": False,
    }
    if email:
        body["EmailAddress"] = email.strip()
    if tax_id:
        body["TaxNumber"] = tax_id.strip()

    try:
        response = await client.post_json("Contacts", json_body={"Contacts": [body]})
    except XeroApiError:
        raise

    contacts = response.get("Contacts") or []
    if not contacts:
        raise ValueError("Xero returned no contact")
    created = contacts[0]
    contact_id = str(created.get("ContactID") or "").strip()
    if not contact_id:
        raise ValueError("Xero contact missing ContactID")

    # Persist into local cache immediately (must flush before mapping validation).
    db.add(
        XeroContact(
            tenant_id=tenant_id,
            accounting_integration_id=integration.id,
            xero_tenant_id=xero_tenant_id,
            xero_contact_id=contact_id,
            name=str(created.get("Name") or legal_name)[:255],
            email_address=(created.get("EmailAddress") or email or None),
            tax_number=(created.get("TaxNumber") or tax_id or None),
            is_supplier=True,
            contact_status=str(created.get("ContactStatus") or "ACTIVE"),
            mapping_status=MAPPING_MAPPED,
            sync_status="active",
            raw_payload_json=None,
        )
    )
    await db.flush()
    await save_supplier_contact_mapping(
        db,
        tenant_id=tenant_id,
        supplier_key=supplier_key,
        legal_name=legal_name,
        contact_id=contact_id,
        user_id=user_id,
        xero_tenant_id=xero_tenant_id,
    )
    await db.flush()
    return {
        "created": True,
        "reused": False,
        "contact_id": contact_id,
        "name": created.get("Name"),
    }


async def ensure_invoice_xero_supplier_contact(
    db: AsyncSession,
    invoice: Any,
) -> dict[str, Any] | None:
    """Match extracted AP vendor to Xero contacts, or create the name in Xero.

    No-op when Xero is not connected, the invoice is sales/vault, or there is no vendor name.
    Never raises — processing must continue.
    """
    from app.services.invoice.invoice_evaluation_service import ROUTE_SALES, ROUTE_VAULT
    from app.utils.logger import get_logger

    log = get_logger(__name__)
    route = (getattr(invoice, "route_target", None) or "").strip()
    if route in {ROUTE_SALES, ROUTE_VAULT}:
        return None
    legal_name = (getattr(invoice, "vendor", None) or "").strip()
    if not legal_name:
        return None
    tenant_id = invoice.tenant_id
    supplier_key = str(getattr(invoice, "storage_vendor_slug", None) or legal_name)
    try:
        await require_xero_ready(db, tenant_id)
    except Exception:
        return None
    try:
        return await create_xero_supplier_contact(
            db,
            tenant_id=tenant_id,
            supplier_key=supplier_key,
            legal_name=legal_name,
            tax_id=getattr(invoice, "abn", None),
            email=getattr(invoice, "email_sender", None),
            user_id=None,
        )
    except Exception as exc:
        log.warning(
            "xero_invoice_contact_ensure_failed",
            invoice_id=getattr(invoice, "id", None),
            tenant_id=str(tenant_id),
            error=str(exc),
        )
        return None
