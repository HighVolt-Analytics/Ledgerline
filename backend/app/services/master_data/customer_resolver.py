"""Resolve customer slug from email sender (capture registry routing)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG, _sender_matches, slugify_vendor_name


async def resolve_customer_slug(
    session: AsyncSession,
    sender: str,
    *,
    tenant_id: uuid.UUID | int | str,
) -> str:
    """Match inbound sender against customer_registry.sender_pattern."""
    if not sender.strip():
        return UNKNOWN_SLUG

    rows = (
        await session.execute(
            select(CustomerRegistry).where(CustomerRegistry.tenant_id == tenant_id)
        )
    ).scalars().all()
    exact: CustomerRegistry | None = None
    domain: CustomerRegistry | None = None
    for row in rows:
        if not _sender_matches(sender, row.sender_pattern):
            continue
        pat = row.sender_pattern.lower().strip()
        if "@" in pat and not pat.startswith("@"):
            if sender.lower() == pat:
                exact = row
                break
        elif domain is None:
            domain = row
    match = exact or domain
    return match.customer_slug if match else UNKNOWN_SLUG


def slug_for_parsed_customer(customer_name: str | None) -> str:
    if not customer_name or not customer_name.strip():
        return UNKNOWN_SLUG
    return slugify_vendor_name(customer_name)


async def resolve_capture_slug(
    session: AsyncSession,
    sender: str,
    *,
    tenant_id: uuid.UUID | int | str,
) -> str:
    """Resolve storage slug from vendor then customer capture registries."""
    from app.services.master_data.vendor_resolver import resolve_vendor_slug

    slug = await resolve_vendor_slug(session, sender, tenant_id=tenant_id)  # type: ignore[arg-type]
    if slug != UNKNOWN_SLUG:
        return slug
    return await resolve_customer_slug(session, sender, tenant_id=tenant_id)
