"""Rule book config CRUD and evaluation."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.models.audit import AuditLog
from app.schemas.common import ApiEnvelope
from app.schemas.rule_book_changelog import RuleBookChangelogEntry
from app.schemas.rule_book_config import (
    RuleBookConfigPayload,
    RuleBookRulesPayload,
    validate_rule_book_config_payload,
)
from app.schemas.rule_book_evaluate import (
    RuleBookEvaluateRequest,
    RuleBookEvaluateResponse,
)
from app.services.master_data_service import attach_masters_to_config_dict, sync_masters_to_config_file
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book_evaluate_service import evaluate_rule_book
from app.services.rule_book_save_buffer import (
    get_buffered_rule_book_raw,
    schedule_rule_book_save,
)

router = APIRouter(prefix="/rule-book", tags=["rule-book"])


def _validation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(422, str(exc))
    return HTTPException(400, str(exc))


async def _load_rule_book_response_dict(
    db: AsyncSession,
    org_id: int,
) -> dict[str, Any]:
    buffered = get_buffered_rule_book_raw(org_id)
    if buffered is not None:
        data = buffered
    else:
        try:
            data = load_rule_book_config_dict(org_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"Invalid rule book config JSON: {exc}") from exc

        try:
            data = validate_rule_book_config_payload(data).model_dump()
        except (ValidationError, ValueError):
            pass

    return await attach_masters_to_config_dict(db, org_id, data)


@router.get("/config", response_model=ApiEnvelope[dict[str, Any]])
async def get_rule_book_config(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Return the rule book config for the current organisation."""
    return ApiEnvelope(data=await _load_rule_book_response_dict(db, ctx.org_id))


@router.put("/config", response_model=ApiEnvelope[dict[str, Any]])
async def put_rule_book_config(
    body: RuleBookRulesPayload,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Buffer rule book changes; commit after server-side debounce (audit + remap once)."""
    try:
        load_rule_book_config_dict(ctx.org_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    try:
        raw = body.model_dump()
        raw["vendor_masters"] = []
        raw["employee_masters"] = []
        payload = validate_rule_book_config_payload(raw)
    except (ValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc

    after_raw = payload.model_dump()
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None

    await schedule_rule_book_save(
        org_id=ctx.org_id,
        payload=payload,
        after_raw=after_raw,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
        db=db,
    )

    data = await attach_masters_to_config_dict(db, ctx.org_id, after_raw)
    return ApiEnvelope(data=data)


@router.get("/changelog", response_model=ApiEnvelope[list[RuleBookChangelogEntry]])
async def get_rule_book_changelog(
    limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[list[RuleBookChangelogEntry]]:
    """Recent rule book saves and invoice remaps for the current organisation."""
    rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.org_id == ctx.org_id,
                AuditLog.event.in_(("rule_book_updated", "invoices_remapped")),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return ApiEnvelope(
        data=[RuleBookChangelogEntry.model_validate(row) for row in rows]
    )


async def _draft_config_with_masters(
    db: AsyncSession,
    org_id: int,
    draft: RuleBookRulesPayload,
) -> RuleBookConfigPayload:
    raw = draft.model_dump()
    raw = await attach_masters_to_config_dict(db, org_id, raw)
    return validate_rule_book_config_payload(raw)


@router.post("/evaluate", response_model=ApiEnvelope[RuleBookEvaluateResponse])
async def evaluate_rule_book_config(
    body: RuleBookEvaluateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[RuleBookEvaluateResponse]:
    """Evaluate draft or saved config against org invoices (preview only)."""
    try:
        config_override = None
        if body.config is not None:
            config_override = await _draft_config_with_masters(db, ctx.org_id, body.config)
        result = await evaluate_rule_book(
            db,
            org_id=ctx.org_id,
            config_override=config_override,
            invoice_ids=body.invoice_ids,
            limit=body.limit,
        )
        return ApiEnvelope(data=RuleBookEvaluateResponse.model_validate(result))
    except (ValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc
