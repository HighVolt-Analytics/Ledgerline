"""Public vendor/employee master confirmation endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiEnvelope
from app.schemas.master_data import (
    MasterConfirmationPreviewResponse,
    MasterConfirmationSaveRequest,
    MasterConfirmationSaveResponse,
    MasterConfirmationSendResponse,
)
from app.services.master_data.master_confirmation_service import (
    preview_master_confirmation,
    save_master_confirmation,
    send_master_confirmation,
)

router = APIRouter(prefix="/master-confirm", tags=["master-confirm"])


@router.get("/preview", response_model=ApiEnvelope[MasterConfirmationPreviewResponse])
async def master_confirm_preview(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[MasterConfirmationPreviewResponse]:
    preview = await preview_master_confirmation(db, token=token)
    return ApiEnvelope(
        data=MasterConfirmationPreviewResponse(
            kind=preview.kind,
            master_id=preview.master_id,
            party_name=preview.party_name,
            tenant_name=preview.tenant_name,
            expired=preview.expired,
            confirmed=preview.confirmed,
            fields=preview.fields,
        )
    )


@router.post("/save", response_model=ApiEnvelope[MasterConfirmationSaveResponse])
async def master_confirm_save(
    body: MasterConfirmationSaveRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[MasterConfirmationSaveResponse]:
    if not body.token.strip():
        raise HTTPException(400, "Token is required")
    result = await save_master_confirmation(db, token=body.token, fields=body.fields)
    return ApiEnvelope(
        data=MasterConfirmationSaveResponse(
            kind=result.kind,
            master_id=result.master_id,
            party_name=result.party_name,
            status=result.status,
            confirmed_at=result.confirmed_at,
        )
    )


def send_response(result) -> ApiEnvelope[MasterConfirmationSendResponse]:
    return ApiEnvelope(
        data=MasterConfirmationSendResponse(
            sent=result.sent,
            email=result.email,
            error=result.error,
            expires_at=result.expires_at,
        )
    )
