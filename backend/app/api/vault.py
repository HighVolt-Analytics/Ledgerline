"""Vault folder tree backed by invoice metadata and Azure blob paths."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.vault import VaultMigrateResponse, VaultTreeResponse
from app.services.vault_service import get_vault_tree_for_tenant, migrate_vault_for_tenant

router = APIRouter(prefix="/vault", tags=["vault"])


@router.get("/tree", response_model=ApiEnvelope[VaultTreeResponse])
async def get_vault_tree(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VaultTreeResponse]:
    """Folder tree for stored invoice files (excludes duplicate_skipped and file-less rows)."""
    data = await get_vault_tree_for_tenant(db, tenant_id=ctx.tenant_id)
    return ApiEnvelope(data=data)


@router.post("/migrate", response_model=ApiEnvelope[VaultMigrateResponse])
async def migrate_vault_blobs(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VaultMigrateResponse]:
    """Move this org's invoice blobs into invoice/{org}/{book}/{vendor}/{year}/{month}/."""
    data = await migrate_vault_for_tenant(db, ctx.tenant_id)
    await db.commit()
    return ApiEnvelope(data=data)
