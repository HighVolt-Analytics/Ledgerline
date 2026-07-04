"""Global login identity lookup."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def resolve_login_account(session: AsyncSession, email: str) -> AuthAccount | None:
    normalized = email.lower().strip()
    logger.info("login_resolve_account_started", email=normalized)

    account = (
        await session.execute(
            select(AuthAccount).where(AuthAccount.email == normalized)
        )
    ).scalar_one_or_none()

    if account is None:
        logger.info("login_resolve_account_not_found", email=normalized)
        return None

    logger.info(
        "login_resolve_account_found",
        email=normalized,
        auth_account_id=account.id,
        is_blocked=account.is_blocked,
    )
    return account
