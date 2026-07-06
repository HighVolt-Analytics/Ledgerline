"""Reset an auth account password (local dev / non-production only).

Usage (from backend/ with venv active):

    python scripts/reset_login_password.py vishnu@highvolt.tech "YourNewPassword"
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select, update

from app.config import get_settings
from app.database import async_session_factory
from app.models.auth_account import AuthAccount
from app.models.user import User
from app.services.auth_service import hash_password


async def reset_password(email: str, new_password: str) -> None:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to reset passwords when APP_ENV is production.")
        sys.exit(1)

    normalized = email.lower().strip()
    if not normalized or not new_password:
        print("Email and password are required.")
        sys.exit(1)

    hashed = hash_password(new_password)
    async with async_session_factory() as session:
        account = (
            await session.execute(select(AuthAccount).where(AuthAccount.email == normalized))
        ).scalar_one_or_none()
        if account is None:
            print(f"No auth account for {normalized}.")
            print("Registered login emails can be listed with:")
            print("  python -c \"import asyncio; from sqlalchemy import select; ...\"")
            sys.exit(1)

        account.password_hash = hashed
        await session.execute(
            update(User).where(User.email == normalized).values(password_hash=hashed)
        )
        await session.commit()
        print(f"Password updated for {normalized} (auth_account id={account.id}).")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    asyncio.run(reset_password(sys.argv[1], sys.argv[2]))


if __name__ == "__main__":
    main()
