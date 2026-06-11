"""Organisation billing credits API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.billing import BillingPurchaseRequest, BillingSettingsUpdate, BillingStateResponse
from app.schemas.common import ApiEnvelope
from app.services.billing_io import load_billing_for_org, purchase_pack, save_billing_for_org

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("", response_model=ApiEnvelope[BillingStateResponse])
async def get_billing(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BillingStateResponse]:
    return ApiEnvelope(data=load_billing_for_org(ctx.org_id))


@router.patch("", response_model=ApiEnvelope[BillingStateResponse])
async def patch_billing(
    body: BillingSettingsUpdate,
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BillingStateResponse]:
    state = load_billing_for_org(ctx.org_id)
    if body.auto_recharge is not None:
        state.auto_recharge = body.auto_recharge
    if body.threshold is not None:
        state.threshold = body.threshold
    return ApiEnvelope(data=save_billing_for_org(ctx.org_id, state))


@router.post("/purchase", response_model=ApiEnvelope[BillingStateResponse])
async def post_billing_purchase(
    body: BillingPurchaseRequest,
    ctx: AuthContext = Depends(get_auth_context),
    _db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingStateResponse]:
    try:
        state = purchase_pack(ctx.org_id, body.pack_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=state)
