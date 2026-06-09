"""Organisation membership helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation import Organisation
from app.models.user_org_membership import UserOrgMembership


async def ensure_membership(session: AsyncSession, *, user_id: int, org_id: int) -> None:
    existing = (
        await session.execute(
            select(UserOrgMembership).where(
                UserOrgMembership.user_id == user_id,
                UserOrgMembership.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return
    session.add(UserOrgMembership(user_id=user_id, org_id=org_id))
    await session.flush()


async def user_has_org_access(session: AsyncSession, *, user_id: int, org_id: int) -> bool:
    row = (
        await session.execute(
            select(UserOrgMembership.id).where(
                UserOrgMembership.user_id == user_id,
                UserOrgMembership.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def list_user_organisations(
    session: AsyncSession, *, user_id: int | None, current_org_id: int
) -> list[Organisation]:
    if user_id is None:
        org = await session.get(Organisation, current_org_id)
        return [org] if org else []

    rows = (
        await session.execute(
            select(Organisation)
            .join(UserOrgMembership, UserOrgMembership.org_id == Organisation.id)
            .where(UserOrgMembership.user_id == user_id)
            .order_by(Organisation.name)
        )
    ).scalars().all()

    if rows:
        return list(rows)

    org = await session.get(Organisation, current_org_id)
    return [org] if org else []
