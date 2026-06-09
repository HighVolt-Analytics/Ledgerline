"""Organisations (tenants) available to the signed-in user."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.organisation import Organisation
from app.schemas.common import ApiEnvelope
from app.schemas.organisation import CreateOrganisationRequest, OrganisationResponse
from app.services.org_membership import ensure_membership, list_user_organisations

router = APIRouter(prefix="/organisations", tags=["organisations"])


def _to_response(org: Organisation, *, current_org_id: int) -> OrganisationResponse:
    return OrganisationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        currency="AUD",
        is_current=org.id == current_org_id,
    )


@router.get("", response_model=ApiEnvelope[list[OrganisationResponse]])
async def list_my_organisations(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[OrganisationResponse]]:
    """Tenants the current user can access."""
    orgs = await list_user_organisations(
        db, user_id=ctx.user_id, current_org_id=ctx.org_id
    )
    return ApiEnvelope(
        data=[_to_response(org, current_org_id=ctx.org_id) for org in orgs]
    )


@router.post("", response_model=ApiEnvelope[OrganisationResponse], status_code=201)
async def create_organisation(
    body: CreateOrganisationRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[OrganisationResponse]:
    """
    Create a new tenant and grant the current user access (demo multi-org).

    Data is isolated per org_id. Switch to the new org via POST /api/auth/switch-org.
    """
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to create an organisation")

    slug = body.slug.strip().lower()
    taken = (
        await db.execute(select(Organisation).where(Organisation.slug == slug))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(409, f"Organisation slug '{slug}' is already taken")

    org = Organisation(name=body.name.strip(), slug=slug)
    db.add(org)
    await db.flush()
    await ensure_membership(db, user_id=ctx.user_id, org_id=org.id)

    return ApiEnvelope(
        data=_to_response(org, current_org_id=ctx.org_id),
    )
