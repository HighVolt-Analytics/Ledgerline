"""Reset login password for an email (AuthAccount + all User rows).

Usage (from backend/):
    python scripts/reset_auth_password.py vishnu@highvolt.tech password123
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.database import async_session_factory
from app.models.auth_account import AuthAccount
from app.models.user import User
from app.services.auth_service import hash_password


async def reset_password(email: str, password: str) -> None:
    normalized = email.lower().strip()
    if not normalized or not password:
        raise SystemExit("Email and password are required")

    password_hash = hash_password(password)
    async with async_session_factory() as session:
        account = (
            await session.execute(
                select(AuthAccount).where(AuthAccount.email == normalized)
            )
        ).scalar_one_or_none()
        if account is None:
            account = AuthAccount(email=normalized, password_hash=password_hash)
            session.add(account)
            await session.flush()
            print(f"Created AuthAccount for {normalized}")
        else:
            account.password_hash = password_hash
            account.is_blocked = False
            print(f"Updated AuthAccount for {normalized}")

        users = (
            await session.execute(select(User).where(User.email.ilike(normalized)))
        ).scalars().all()
        for user in users:
            user.password_hash = password_hash
            if user.auth_account_id is None:
                user.auth_account_id = account.id
        print(f"Synced {len(users)} user row(s)")
        await session.commit()
    print("Done. Sign in with the new password; OTP in dev is 123456.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/reset_auth_password.py <email> <password>")
    asyncio.run(reset_password(sys.argv[1], sys.argv[2]))
