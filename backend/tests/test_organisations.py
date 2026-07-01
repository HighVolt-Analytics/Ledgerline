"""Tenant membership and org switching APIs."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_test_helpers import seed_admin_user


@pytest.mark.asyncio
async def test_list_tenants_and_switch_denied_for_extra_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await seed_admin_user(
        db_session,
        email="demo-parent@test.com",
        tenant_slug="hv-org",
        full_name="Demo Admin",
    )
    await db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}

    listed = await client.get("/api/tenants", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1

    created = await client.post(
        "/api/tenants",
        headers=headers,
        json={"name": "Demo Child Co", "slug": "demo-child"},
    )
    assert created.status_code == 403
