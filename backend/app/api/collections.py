"""Collections (AR) API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.schemas.collection import (
    CollectionMarkReceivedRequest,
    CollectionResponse,
    CollectionWorkspaceKpis,
)
from app.schemas.common import ApiEnvelope
from app.services.audit.audit_service import log_event
from app.services.integration.collection_service import (
    collection_workspace_kpis,
    list_collections,
    mark_collection_received,
)

router = APIRouter(prefix="/collections", tags=["collections"])

_LIST_LIMIT_MAX = 200


@router.get("/kpis", response_model=ApiEnvelope[CollectionWorkspaceKpis])
async def get_collection_workspace_kpis(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CollectionWorkspaceKpis]:
    data = await collection_workspace_kpis(db, ctx.tenant_id, tenant=ctx.tenant)
    return ApiEnvelope(data=data)


@router.get("", response_model=ApiEnvelope[list[CollectionResponse]])
async def get_collections(
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=_LIST_LIMIT_MAX),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[CollectionResponse]]:
    try:
        rows = await list_collections(db, ctx.tenant_id, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=rows)


@router.post(
    "/{collection_id}/mark-received",
    response_model=ApiEnvelope[CollectionResponse],
)
async def post_mark_collection_received(
    collection_id: int,
    body: CollectionMarkReceivedRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CollectionResponse]:
    try:
        row = await mark_collection_received(
            db,
            ctx.tenant_id,
            collection_id,
            received_date=None,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "collection_received",
        invoice_id=row.invoice_id,
        tenant_id=ctx.tenant_id,
        actor_name=actor_name,
        actor_email=actor_email,
        detail={
            "collection_id": collection_id,
            "amount": row.amount,
            "note": body.note,
        },
    )
    return ApiEnvelope(data=row)
