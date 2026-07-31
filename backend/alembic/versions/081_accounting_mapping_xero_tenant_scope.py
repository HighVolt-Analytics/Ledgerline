"""Scope accounting_entity_mappings by Xero organisation.

Revision ID: 081
Revises: 080

Adds xero_tenant_id, replaces uniqueness with
tenant_id + provider + xero_tenant_id + mapping_type + source_key,
and backfills from the currently selected Xero organisation when safe.
Unsafe mappings are left inactive and require remapping.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "081"
down_revision: Union[str, None] = "080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def _has_unique(conn, table: str, name: str) -> bool:
    return any(uc["name"] == name for uc in inspect(conn).get_unique_constraints(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "accounting_entity_mappings"):
        return

    if not _has_column(conn, "accounting_entity_mappings", "xero_tenant_id"):
        op.add_column(
            "accounting_entity_mappings",
            sa.Column(
                "xero_tenant_id",
                sa.String(length=128),
                nullable=False,
                server_default="",
            ),
        )

    # Backfill from selected organisation when exactly one selected tenant id exists.
    # Validate GL / tax / supplier / tracking against that org's active reference rows.
    # Failures → is_active=false (still assign selected org id when known).
    conn.execute(
        text(
            """
            UPDATE accounting_entity_mappings AS m
            SET xero_tenant_id = COALESCE(
                (
                    SELECT ai.provider_tenant_id
                    FROM accounting_integrations AS ai
                    WHERE ai.tenant_id = m.tenant_id
                      AND ai.provider = 'xero'
                      AND ai.provider_tenant_id IS NOT NULL
                      AND TRIM(ai.provider_tenant_id) <> ''
                    LIMIT 1
                ),
                ''
            )
            WHERE m.xero_tenant_id = '' OR m.xero_tenant_id IS NULL
            """
        )
    )

    # Deactivate mappings with no determinable organisation.
    conn.execute(
        text(
            """
            UPDATE accounting_entity_mappings
            SET is_active = false
            WHERE TRIM(COALESCE(xero_tenant_id, '')) = ''
            """
        )
    )

    # Deactivate GL mappings whose AccountCode is not active for the assigned org.
    conn.execute(
        text(
            """
            UPDATE accounting_entity_mappings AS m
            SET is_active = false
            WHERE m.mapping_type = 'gl_account'
              AND m.is_active IS TRUE
              AND TRIM(COALESCE(m.xero_tenant_id, '')) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM xero_accounts AS a
                WHERE a.tenant_id = m.tenant_id
                  AND a.xero_tenant_id = m.xero_tenant_id
                  AND a.code = m.external_code
                  AND a.sync_status = 'active'
              )
            """
        )
    )

    # Deactivate tax mappings whose TaxType is not active for the assigned org.
    conn.execute(
        text(
            """
            UPDATE accounting_entity_mappings AS m
            SET is_active = false
            WHERE m.mapping_type = 'tax_code'
              AND m.is_active IS TRUE
              AND TRIM(COALESCE(m.xero_tenant_id, '')) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM xero_tax_rates AS t
                WHERE t.tenant_id = m.tenant_id
                  AND t.xero_tenant_id = m.xero_tenant_id
                  AND t.tax_type = COALESCE(m.external_code, m.external_id)
                  AND t.sync_status = 'active'
              )
            """
        )
    )

    # Deactivate supplier mappings whose ContactID is not active for the assigned org.
    conn.execute(
        text(
            """
            UPDATE accounting_entity_mappings AS m
            SET is_active = false
            WHERE m.mapping_type = 'supplier'
              AND m.is_active IS TRUE
              AND TRIM(COALESCE(m.xero_tenant_id, '')) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM xero_contacts AS c
                WHERE c.tenant_id = m.tenant_id
                  AND c.xero_tenant_id = m.xero_tenant_id
                  AND c.xero_contact_id = m.external_id
                  AND c.sync_status = 'active'
              )
            """
        )
    )

    # Deactivate tracking mappings whose option is not active for the assigned org.
    conn.execute(
        text(
            """
            UPDATE accounting_entity_mappings AS m
            SET is_active = false
            WHERE m.mapping_type = 'tracking'
              AND m.is_active IS TRUE
              AND TRIM(COALESCE(m.xero_tenant_id, '')) <> ''
              AND NOT EXISTS (
                SELECT 1 FROM xero_tracking_categories AS tc
                WHERE tc.tenant_id = m.tenant_id
                  AND tc.xero_tenant_id = m.xero_tenant_id
                  AND tc.option_external_id = COALESCE(m.external_option_id, m.external_id)
                  AND tc.sync_status = 'active'
                  AND tc.is_active IS TRUE
              )
            """
        )
    )

    if _has_unique(conn, "accounting_entity_mappings", "uq_accounting_entity_mappings_source"):
        op.drop_constraint(
            "uq_accounting_entity_mappings_source",
            "accounting_entity_mappings",
            type_="unique",
        )

    if not _has_unique(
        conn, "accounting_entity_mappings", "uq_accounting_entity_mappings_org_source"
    ):
        op.create_unique_constraint(
            "uq_accounting_entity_mappings_org_source",
            "accounting_entity_mappings",
            [
                "tenant_id",
                "provider",
                "xero_tenant_id",
                "mapping_type",
                "source_key",
            ],
        )

    existing_indexes = {
        idx["name"] for idx in inspect(conn).get_indexes("accounting_entity_mappings")
    }
    if "ix_accounting_entity_mappings_xero_tenant_id" not in existing_indexes:
        op.create_index(
            "ix_accounting_entity_mappings_xero_tenant_id",
            "accounting_entity_mappings",
            ["xero_tenant_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "accounting_entity_mappings"):
        return

    if _has_unique(
        conn, "accounting_entity_mappings", "uq_accounting_entity_mappings_org_source"
    ):
        op.drop_constraint(
            "uq_accounting_entity_mappings_org_source",
            "accounting_entity_mappings",
            type_="unique",
        )

    if not _has_unique(conn, "accounting_entity_mappings", "uq_accounting_entity_mappings_source"):
        op.create_unique_constraint(
            "uq_accounting_entity_mappings_source",
            "accounting_entity_mappings",
            ["tenant_id", "provider", "mapping_type", "source_key"],
        )

    if _has_column(conn, "accounting_entity_mappings", "xero_tenant_id"):
        existing_indexes = {
            idx["name"] for idx in inspect(conn).get_indexes("accounting_entity_mappings")
        }
        if "ix_accounting_entity_mappings_xero_tenant_id" in existing_indexes:
            op.drop_index(
                "ix_accounting_entity_mappings_xero_tenant_id",
                table_name="accounting_entity_mappings",
            )
        op.drop_column("accounting_entity_mappings", "xero_tenant_id")
