"""Platform tenant service tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.services.platform_service import create_client_tenant, list_client_tenants
from app.schemas.platform import CreatePlatformTenantRequest


@pytest.mark.asyncio
async def test_list_client_tenants_excludes_platform_tenant(db_session: AsyncSession) -> None:
    import uuid

    db_session.add(
        Tenant(id=uuid.uuid4(), name="Acme Client", slug="acme-client", is_platform=False)
    )
    db_session.add(
        Tenant(id=uuid.uuid4(), name="LedgerLink Platform", slug="platform", is_platform=True)
    )
    await db_session.flush()

    tenants = await list_client_tenants(db_session)
    slugs = {t.slug for t in tenants}
    assert "platform" not in slugs
    assert "acme-client" in slugs


@pytest.mark.asyncio
async def test_create_client_tenant_seeds_modules(db_session: AsyncSession) -> None:
    tenant = await create_client_tenant(
        db_session,
        CreatePlatformTenantRequest(name="New Client", slug="new-client"),
    )
    assert tenant.slug == "new-client"
    assert len(tenant.modules) == 5
    assert all(m.is_active for m in tenant.modules)
