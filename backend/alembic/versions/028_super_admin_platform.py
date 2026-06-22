"""Super admin role and platform tenant for vishnu@highvolt.tech.

Revision ID: 028
Revises: 027
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SUPER_ADMIN_EMAIL = "vishnu@highvolt.tech"
_PLATFORM_SLUG = "platform"
_DEFAULT_MODULES = ("purchase", "expenses", "team_expenses", "vault", "rule_book")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'super_admin'")

    conn = op.get_bind()

    platform_id = conn.execute(
        sa.text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": _PLATFORM_SLUG},
    ).scalar()

    if platform_id is None:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO tenants (name, slug, is_active, is_platform, lifecycle_status)
                VALUES ('LedgerLink Platform', :slug, true, true, 'active')
                RETURNING id
                """
            ),
            {"slug": _PLATFORM_SLUG},
        )
        platform_id = result.fetchone()[0]

    row = conn.execute(
        sa.text(
            """
            SELECT u.id, u.auth_account_id, u.password_hash, u.full_name
            FROM users u
            WHERE lower(u.email) = :email
            ORDER BY u.id
            LIMIT 1
            """
        ),
        {"email": _SUPER_ADMIN_EMAIL},
    ).fetchone()

    if not row:
        return

    _user_id, auth_account_id, password_hash, full_name = row

    platform_user_id = conn.execute(
        sa.text(
            """
            SELECT id FROM users
            WHERE tenant_id = :tid AND lower(email) = :email
            """
        ),
        {"tid": platform_id, "email": _SUPER_ADMIN_EMAIL},
    ).scalar()

    if platform_user_id is None:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO users (
                    tenant_id, auth_account_id, email, password_hash, full_name, role, is_active
                )
                VALUES (
                    :tid, :aid, :email, :phash, :name, 'super_admin', true
                )
                RETURNING id
                """
            ),
            {
                "tid": platform_id,
                "aid": auth_account_id,
                "email": _SUPER_ADMIN_EMAIL,
                "phash": password_hash,
                "name": full_name or "Vishnu",
            },
        )
        platform_user_id = result.fetchone()[0]
    else:
        conn.execute(
            sa.text(
                """
                UPDATE users
                SET role = 'super_admin', is_active = true, auth_account_id = :aid
                WHERE id = :uid
                """
            ),
            {"uid": platform_user_id, "aid": auth_account_id},
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO user_tenant_mappings (
                user_id, tenant_id, role, status, default_tenant, is_active
            )
            VALUES (:uid, :tid, 'super_admin', 'active', true, true)
            ON CONFLICT ON CONSTRAINT uq_user_tenant
            DO UPDATE SET
                role = 'super_admin',
                status = 'active',
                is_active = true,
                default_tenant = true
            """
        ),
        {"uid": platform_user_id, "tid": platform_id},
    )


def downgrade() -> None:
    raise NotImplementedError("028 downgrade not supported")
