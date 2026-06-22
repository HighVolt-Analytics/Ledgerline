"""Global login identity lookup."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount


async def resolve_login_account(session: AsyncSession, email: str) -> AuthAccount | None:
    return (
        await session.execute(
            select(AuthAccount).where(AuthAccount.email == email.lower().strip())
        )
    ).scalar_one_or_none()
