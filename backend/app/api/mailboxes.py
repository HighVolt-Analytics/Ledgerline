"""Connected Outlook mailboxes for the organisation."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_context, get_db, require_admin
from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice
from app.schemas.common import ApiEnvelope
from app.schemas.mailbox import MailboxCreate, MailboxResponse

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


@router.get("", response_model=ApiEnvelope[list[MailboxResponse]])
async def list_mailboxes(
    db: AsyncSession = Depends(get_db),
    ctx=Depends(get_auth_context),
) -> ApiEnvelope[list[MailboxResponse]]:
    rows = (
        await db.execute(
            select(ConnectedMailbox)
            .where(ConnectedMailbox.org_id == ctx.org_id)
            .order_by(ConnectedMailbox.email)
        )
    ).scalars().all()
    return ApiEnvelope(data=[MailboxResponse.model_validate(r) for r in rows])


@router.post("", response_model=ApiEnvelope[MailboxResponse], status_code=201)
async def add_mailbox(
    body: MailboxCreate,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> ApiEnvelope[MailboxResponse]:
    email = body.email.lower().strip()
    existing = (
        await db.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.org_id == ctx.org_id,
                ConnectedMailbox.email == email,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Mailbox '{email}' is already connected")

    row = ConnectedMailbox(
        org_id=ctx.org_id,
        email=email,
        display_name=body.display_name or email,
        is_active=True,
    )
    db.add(row)
    await db.flush()
    return ApiEnvelope(data=MailboxResponse.model_validate(row))


@router.delete("/{mailbox_id}", status_code=204)
async def remove_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> None:
    row = await db.get(ConnectedMailbox, mailbox_id)
    if not row or row.org_id != ctx.org_id:
        raise HTTPException(404, "Mailbox not found")
    await db.execute(
        update(Invoice)
        .where(
            Invoice.org_id == ctx.org_id,
            Invoice.connected_mailbox_id == mailbox_id,
        )
        .values(connected_mailbox_id=None)
    )
    await db.delete(row)
    await db.flush()


@router.patch("/{mailbox_id}/toggle", response_model=ApiEnvelope[MailboxResponse])
async def toggle_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> ApiEnvelope[MailboxResponse]:
    row = await db.get(ConnectedMailbox, mailbox_id)
    if not row or row.org_id != ctx.org_id:
        raise HTTPException(404, "Mailbox not found")
    row.is_active = not row.is_active
    row.last_poll_at = row.last_poll_at or datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(row)
    return ApiEnvelope(data=MailboxResponse.model_validate(row))
