"""Vault folder tree backed by invoice metadata and Azure blob paths."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.vault import (
    VaultDocumentSetsResponse,
    VaultFilesResponse,
    VaultMigrateResponse,
    VaultTreeResponse,
)
from app.services.vault.vault_service import (
    VAULT_PAGE_FILE_LIMIT,
    get_vault_document_sets_for_tenant,
    get_vault_files_for_tenant,
    get_vault_tree_for_tenant,
    migrate_vault_for_tenant,
)

router = APIRouter(prefix="/vault", tags=["vault"])


@router.get("/tree", response_model=ApiEnvelope[VaultTreeResponse])
async def get_vault_tree(
    include_files: bool = Query(
        True,
        description="When false, return folder counts only (first-paint tree).",
    ),
    file_limit: int | None = Query(
        None,
        ge=1,
        le=500,
        description="Cap files in the tree payload. Folder counts stay tenant-wide.",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VaultTreeResponse]:
    """Folder tree for stored invoice files (excludes duplicate_skipped and file-less rows)."""
    data = await get_vault_tree_for_tenant(
        db,
        tenant_id=ctx.tenant_id,
        include_files=include_files,
        file_limit=file_limit,
    )
    return ApiEnvelope(data=data)


@router.get("/files", response_model=ApiEnvelope[VaultFilesResponse])
async def get_vault_files(
    invoice_id: int | None = Query(None, ge=1),
    org: str | None = None,
    book: str | None = None,
    document_type: str | None = None,
    vendor: str | None = None,
    year: str | None = None,
    month: str | None = None,
    po_folder: str | None = None,
    limit: int = Query(VAULT_PAGE_FILE_LIMIT, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VaultFilesResponse]:
    """Files for a folder selection, or a single invoice for vault deep-links."""
    data = await get_vault_files_for_tenant(
        db,
        tenant_id=ctx.tenant_id,
        invoice_id=invoice_id,
        org=org,
        book=book,
        document_type=document_type,
        vendor=vendor,
        year=year,
        month=month,
        po_folder=po_folder,
        limit=limit,
    )
    return ApiEnvelope(data=data)


@router.get("/document-sets", response_model=ApiEnvelope[VaultDocumentSetsResponse])
async def get_vault_document_sets(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VaultDocumentSetsResponse]:
    """Document-set cards with tenant-wide match counts and a capped invoice list."""
    data = await get_vault_document_sets_for_tenant(db, tenant_id=ctx.tenant_id)
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
