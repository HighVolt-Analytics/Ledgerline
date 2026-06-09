"""Organisation membership and demo multi-org APIs."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_list_and_switch_org(client: AsyncClient) -> None:
    reg = await client.post(
        "/api/auth/register",
        json={
            "org_name": "Demo Parent Co",
            "org_slug": "demo-parent",
            "email": "demo-parent@test.com",
            "password": "securepass1",
            "full_name": "Demo Admin",
        },
    )
    assert reg.status_code == 201
    token = reg.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    listed = await client.get("/api/organisations", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1

    created = await client.post(
        "/api/organisations",
        headers=headers,
        json={"name": "Demo Child Co", "slug": "demo-child"},
    )
    assert created.status_code == 201
    child_id = created.json()["data"]["id"]

    listed2 = await client.get("/api/organisations", headers=headers)
    assert len(listed2.json()["data"]) == 2

    switched = await client.post(
        "/api/auth/switch-org",
        headers=headers,
        json={"org_id": child_id},
    )
    assert switched.status_code == 200
    assert switched.json()["data"]["user"]["org_slug"] == "demo-child"
