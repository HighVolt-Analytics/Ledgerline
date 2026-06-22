"""User-level data access within a tenant."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


async def enforce_user_data_access(
    session: AsyncSession,
    current_user: User,
    target_user_id: int,
) -> None:
    del session
    if current_user.id == target_user_id:
        return
    if current_user.role == UserRole.ADMIN:
        return
    raise HTTPException(403, "Access denied")
