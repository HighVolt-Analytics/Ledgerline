"""Supplementary Xero integration routes (production refinement)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.xero_refinement import XeroVerifyResponse
from app.integrations.xero.mapping import XeroMappingValidationError
from app.integrations.xero.verify import verify_xero_connection

router = APIRouter(prefix="/integrations/xero", tags=["accounting-integrations"])


@router.get("/verify", response_model=ApiEnvelope[XeroVerifyResponse])
async def xero_verify(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroVerifyResponse]:
    data = await verify_xero_connection(db, ctx.tenant_id)
    await db.commit()
    return ApiEnvelope(data=XeroVerifyResponse.model_validate(data))


def mapping_validation_http_exception(exc: XeroMappingValidationError) -> HTTPException:
    return HTTPException(422, exc.result.to_dict())
