"""Seed vendor_registry from rule book vendor names."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import VendorRegistry
from app.services.vendor_resolver import slugify_vendor_name

# Known billing senders for rule-book vendors (extend via API).
DEFAULT_VENDORS: list[dict[str, str | bool | None]] = [
    {
        "vendor_slug": "amazon-web-services",
        "vendor_name": "Amazon Web Services",
        "sender_pattern": "@amazonaws.com",
        "abn": "51824753556",
        "approved": True,
    },
    {
        "vendor_slug": "microsoft-azure",
        "vendor_name": "Microsoft Azure",
        "sender_pattern": "@microsoft.com",
        "abn": None,
        "approved": False,
    },
    {
        "vendor_slug": "atlassian",
        "vendor_name": "Atlassian Pty Ltd",
        "sender_pattern": "@atlassian.com",
        "abn": "53102443916",
        "approved": True,
    },
    {
        "vendor_slug": "google-australia",
        "vendor_name": "Google Australia Pty Ltd",
        "sender_pattern": "@google.com",
        "abn": None,
        "approved": False,
    },
    {
        "vendor_slug": "meta-platforms",
        "vendor_name": "Meta Platforms Ireland",
        "sender_pattern": "@facebook.com",
        "abn": "51824753556",
        "approved": True,
    },
    {
        "vendor_slug": "deloitte",
        "vendor_name": "Deloitte Touche Tohmatsu",
        "sender_pattern": "@deloitte.com",
        "abn": None,
        "approved": False,
    },
    {
        "vendor_slug": "qantas",
        "vendor_name": "Qantas Airways Limited",
        "sender_pattern": "@qantas.com.au",
        "abn": None,
        "approved": False,
    },
    {
        "vendor_slug": "hilton-sydney",
        "vendor_name": "Hilton Sydney",
        "sender_pattern": "@hilton.com",
        "abn": None,
        "approved": False,
    },
]


async def seed_vendors(session: AsyncSession, *, org_id: int = 1) -> int:
    """Insert default vendors when slug is not already present."""
    added = 0
    for item in DEFAULT_VENDORS:
        slug = str(item["vendor_slug"])
        exists = (
            await session.execute(
                select(VendorRegistry).where(
                    VendorRegistry.org_id == org_id,
                    VendorRegistry.vendor_slug == slug,
                )
            )
        ).scalar_one_or_none()
        if exists:
            continue
        session.add(
            VendorRegistry(
                org_id=org_id,
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
