"""Tenant billing credits API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request
from app.schemas.billing import BillingPurchaseRequest, BillingSettingsUpdate, BillingStateResponse
from app.schemas.common import ApiEnvelope
from app.services.billing_io import (
    load_billing_for_tenant,
    purchase_pack,
    update_billing_settings,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("", response_model=ApiEnvelope[BillingStateResponse])
async def get_billing(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BillingStateResponse]:
    return ApiEnvelope(data=load_billing_for_tenant(ctx.tenant_id))


@router.patch("", response_model=ApiEnvelope[BillingStateResponse])
async def patch_billing(
    body: BillingSettingsUpdate,
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BillingStateResponse]:
    state = update_billing_settings(
        ctx.tenant_id,
        auto_recharge=body.auto_recharge,
        threshold=body.threshold,
    )
    return ApiEnvelope(data=state)


@router.post("/purchase", response_model=ApiEnvelope[BillingStateResponse])
async def post_billing_purchase(
    body: BillingPurchaseRequest,
    ctx: AuthContext = Depends(get_auth_context),
    _db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingStateResponse]:
    try:
        state = purchase_pack(ctx.tenant_id, body.pack_id)
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return ApiEnvelope(data=state)
