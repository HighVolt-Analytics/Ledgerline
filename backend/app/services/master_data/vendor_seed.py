"""Seed vendor_registry from rule book vendor names."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import VendorRegistry
from app.services.master_data.vendor_resolver import slugify_vendor_name

# Known billing senders for rule-book vendors (extend via API).
DEFAULT_VENDORS: list[dict[str, str | bool | None]] = []


async def seed_vendors(session: AsyncSession, *, tenant_id: int = 1) -> int:
    """Insert default vendors when slug is not already present."""
    added = 0
    for item in DEFAULT_VENDORS:
        slug = str(item["vendor_slug"])
        exists = (
            await session.execute(
                select(VendorRegistry).where(
                    VendorRegistry.tenant_id == tenant_id,
                    VendorRegistry.vendor_slug == slug,
                )
            )
        ).scalar_one_or_none()
        if exists:
            continue
        session.add(
            VendorRegistry(
                tenant_id=tenant_id,
                vendor_slug=slug,
                vendor_name=str(item["vendor_name"]),
                sender_pattern=str(item["sender_pattern"]),
                abn=item.get("abn"),  # type: ignore[arg-type]
                approved=bool(item.get("approved", False)),
            )
        )
        added += 1
    return added


def slug_from_rule_book_name(name: str) -> str:
    return slugify_vendor_name(name)
