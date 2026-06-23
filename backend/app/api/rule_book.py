"""Rule book config CRUD and evaluation."""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.services.privilege_service import require_privilege
from app.models.audit import AuditLog
from app.schemas.common import ApiEnvelope
from app.schemas.rule_book_changelog import RuleBookChangelogEntry
from app.schemas.rule_book_config import (
    RuleBookConfigPayload,
    RuleBookRulesPayload,
    validate_rule_book_config_payload,
)
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.document_type_sample_analysis import DocumentTypeSampleProposal
from app.schemas.rule_book_evaluate import (
    RuleBookEvaluateRequest,
    RuleBookEvaluateResponse,
)
from app.services.document_type_sample_analyzer import analyze_document_type_samples
from app.services.document_type_classify_preview import (
    classify_samples_against_catalog,
    merge_draft_document_type,
)
from app.services.master_data_service import attach_masters_to_config_dict
from app.services.invoice_evaluation_service import load_config_for_tenant
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book_evaluate_service import evaluate_rule_book
from app.services.rule_book_save_buffer import (
    get_buffered_rule_book_raw,
    schedule_rule_book_save,
)

router = APIRouter(prefix="/rule-book", tags=["rule-book"])

_MAX_SAMPLE_BYTES = 25 * 1024 * 1024
_MAX_SAMPLE_FILES = 10


def _validation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(422, str(exc))
    return HTTPException(400, str(exc))


async def _load_rule_book_response_dict(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    buffered = get_buffered_rule_book_raw(tenant_id)
    if buffered is not None:
        data = buffered
    else:
        try:
            data = await load_rule_book_config_dict(db, tenant_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"Invalid rule book config JSON: {exc}") from exc

        try:
            data = validate_rule_book_config_payload(data).model_dump()
        except (ValidationError, ValueError):
            pass

    return await attach_masters_to_config_dict(db, tenant_id, data)


@router.get("/config", response_model=ApiEnvelope[dict[str, Any]])
async def get_rule_book_config(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Return the rule book config for the current organisation."""
    return ApiEnvelope(data=await _load_rule_book_response_dict(db, ctx.tenant_id))


@router.put("/config", response_model=ApiEnvelope[dict[str, Any]])
async def put_rule_book_config(
    body: RuleBookRulesPayload,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Buffer rule book changes; commit after server-side debounce (audit + remap once)."""
    require_privilege(ctx, "Edit Policy")
    await load_rule_book_config_dict(db, ctx.tenant_id)

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
        tenant_id=ctx.tenant_id,
        payload=payload,
        after_raw=after_raw,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
        db=db,
    )

    data = await attach_masters_to_config_dict(db, ctx.tenant_id, after_raw)
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
                AuditLog.tenant_id == ctx.tenant_id,
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
    tenant_id: uuid.UUID,
    draft: RuleBookRulesPayload,
) -> RuleBookConfigPayload:
    raw = draft.model_dump()
    raw = await attach_masters_to_config_dict(db, tenant_id, raw)
    return validate_rule_book_config_payload(raw)


async def _read_sample_upload(file: UploadFile) -> tuple[str, bytes]:
    name = (file.filename or "sample.pdf").strip() or "sample.pdf"
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await file.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > _MAX_SAMPLE_BYTES:
            raise HTTPException(413, f"File too large (max {_MAX_SAMPLE_BYTES // (1024 * 1024)} MB)")
        chunks.append(block)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(400, f"Empty file: {name}")
    return name, content


@router.post(
    "/document-types/analyze-samples",
    response_model=ApiEnvelope[DocumentTypeSampleProposal],
)
async def analyze_document_type_samples_endpoint(
    files: list[UploadFile] = File(...),
    purchase_bundle_role: str = Form(""),
    expected_document_type_code: str = Form(""),
    draft_document_type_json: str = Form(""),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[DocumentTypeSampleProposal]:
    """Parse sample PDFs/images and propose document-type settings (deterministic OCR)."""
    require_privilege(ctx, "Edit Policy")
    if not files:
        raise HTTPException(400, "At least one sample file is required")
    if len(files) > _MAX_SAMPLE_FILES:
        raise HTTPException(400, f"At most {_MAX_SAMPLE_FILES} sample files allowed")

    uploads: list[tuple[str, bytes]] = []
    for upload in files:
        uploads.append(await _read_sample_upload(upload))

    try:
        proposal = analyze_document_type_samples(
            uploads,
            purchase_bundle_role=purchase_bundle_role,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    draft_type: DocumentTypeDefinition | None = None
    if draft_document_type_json.strip():
        try:
            draft_type = DocumentTypeDefinition.model_validate_json(draft_document_type_json)
        except ValidationError as exc:
            raise HTTPException(422, f"Invalid draft document type: {exc}") from exc

    try:
        config = await load_config_for_tenant(db, ctx.tenant_id)
    except FileNotFoundError:
        config = None

    if config is not None:
        catalogue = merge_draft_document_type(config.document_types, draft_type)
        expected = expected_document_type_code.strip() or (
            draft_type.code.strip() if draft_type else ""
        )
        previews = classify_samples_against_catalog(
            uploads,
            document_types=catalogue,
            unclassified=config.document_classification,
            expected_code=expected or None,
        )
        preview_by_name = {item.filename: item for item in previews}
        enriched_samples = []
        for sample in proposal.samples:
            preview = preview_by_name.get(sample.filename)
            if preview is None:
                enriched_samples.append(sample)
                continue
            enriched_samples.append(
                sample.model_copy(
                    update={
                        "routed_code": preview.routed_code or None,
                        "routed_confidence": preview.routed_confidence,
                        "route_needs_review": preview.needs_review,
                        "route_conflicts": preview.conflicts,
                        "matches_expected": preview.matches_expected,
                        "route_alternatives": [
                            {
                                "code": alt.code,
                                "confidence": alt.confidence,
                                "reason": alt.reason,
                                "needs_review": alt.needs_review,
                                "priority": alt.priority,
                            }
                            for alt in preview.alternatives
                        ],
                    }
                )
            )
        proposal = proposal.model_copy(update={"samples": enriched_samples})
        mismatched = [
            row.filename
            for row in enriched_samples
            if row.matches_expected is False
        ]
        if mismatched:
            proposal.notes.append(
                "Catalogue routing mismatch for: "
                + ", ".join(mismatched)
                + ". Apply suggestions, save, and re-analyze if needed."
            )

    return ApiEnvelope(data=proposal)


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
            config_override = await _draft_config_with_masters(db, ctx.tenant_id, body.config)
        result = await evaluate_rule_book(
            db,
            tenant_id=ctx.tenant_id,
            config_override=config_override,
            invoice_ids=body.invoice_ids,
            limit=body.limit,
        )
        return ApiEnvelope(data=RuleBookEvaluateResponse.model_validate(result))
    except (ValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc
