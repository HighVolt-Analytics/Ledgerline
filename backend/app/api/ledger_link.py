"""Ledger Link — journal overview and export register."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.ledger_link import LedgerLinkResponse
from app.services.ledger_link_service import build_ledger_link

router = APIRouter(prefix="/ledger-link", tags=["ledger-link"])


@router.get("", response_model=ApiEnvelope[LedgerLinkResponse])
async def get_ledger_link(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[LedgerLinkResponse]:
    data = await build_ledger_link(db, org_id=ctx.org_id)
    return ApiEnvelope(data=data)
