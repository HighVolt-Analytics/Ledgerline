"""QuickBooks Online pulled-contact APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_admin
from app.integrations.qbo.client import QboApiError
from app.integrations.qbo.contacts import create_contact, list_contacts, sync_contacts
from app.integrations.qbo.store import QboNotReadyError
from app.schemas.common import ApiEnvelope
from app.services.audit.audit_service import log_event

router = APIRouter(prefix="/integrations/quickbooks", tags=["quickbooks-contacts"])


class ContactCreateBody(BaseModel):
    legal_name: str
    entity_type: str = "vendor"
    given_name: str | None = None
    family_name: str | None = None
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    tax_identifier: str | None = None


@router.get("/contacts")
async def qbo_contacts(
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        data = await list_contacts(
            db,
            tenant_id=ctx.tenant_id,
            search=search,
            limit=limit,
            offset=offset,
        )
    except QboNotReadyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=data)


@router.post("/contacts/sync")
async def qbo_sync_contacts(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        counts = await sync_contacts(db, ctx.tenant_id)
    except QboNotReadyError as exc:
        raise HTTPException(400, str(exc)) from exc
    except QboApiError as exc:
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    counts["committed"] = True
    return ApiEnvelope(data=counts)


@router.post("/contacts/create")
async def qbo_create_contact(
    body: ContactCreateBody,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        result = await create_contact(
            db,
            tenant_id=ctx.tenant_id,
            display_name=body.legal_name,
            entity_type=body.entity_type,
            given_name=body.given_name,
            family_name=body.family_name,
            company_name=body.company_name,
            email=body.email,
            phone=body.phone,
            tax_identifier=body.tax_identifier,
        )
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(400, detail={"message": code, "code": code}) from exc
    except QboNotReadyError as exc:
        raise HTTPException(400, str(exc)) from exc
    except QboApiError as exc:
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await log_event(
        db,
        "qbo_contact_created",
        tenant_id=ctx.tenant_id,
        detail=result,
    )
    await db.commit()
    return ApiEnvelope(data=result)
