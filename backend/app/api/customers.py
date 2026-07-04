"""Customer registry CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_not_found
from app.schemas.common import ApiEnvelope
from app.schemas.customer import CustomerCreate, CustomerResponse, CustomerUpdate
from app.services.master_data.customer_registry_service import (
    create_customer_registry,
    delete_customer_registry,
    list_customer_registry,
    update_customer_registry,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=ApiEnvelope[list[CustomerResponse]])
async def list_customers(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[CustomerResponse]]:
    return ApiEnvelope(data=await list_customer_registry(db, tenant_id=ctx.tenant_id))


@router.post("", response_model=ApiEnvelope[CustomerResponse], status_code=201)
async def create_customer(
    body: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CustomerResponse]:
    try:
        row = await create_customer_registry(db, tenant_id=ctx.tenant_id, body=body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.patch("/{customer_id}", response_model=ApiEnvelope[CustomerResponse])
async def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CustomerResponse]:
    try:
        row = await update_customer_registry(
            db, tenant_id=ctx.tenant_id, customer_id=customer_id, body=body
        )
    except LookupError as exc:
        raise http_not_found(exc) from exc
    return ApiEnvelope(data=row)


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    try:
        await delete_customer_registry(db, tenant_id=ctx.tenant_id, customer_id=customer_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
