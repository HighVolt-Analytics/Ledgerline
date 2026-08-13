"""Rule book config CRUD and evaluation."""

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.services.auth.privilege_service import require_privilege
from app.models.audit import AuditLog
from app.schemas.common import ApiEnvelope
from app.schemas.rule_book_changelog import RuleBookChangelogEntry
from app.schemas.rule_book_config import (
    RuleBookConfigPayload,
    RuleBookDocumentTypeInvariantError,
    RuleBookPostToValidationError,
    RuleBookRulesPayload,
    validate_rule_book_config_for_save,
    validate_rule_book_config_payload,
)
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.document_type_sample_analysis import DocumentTypeSampleProposal
from app.schemas.recognition_signal_catalog import RecognitionSignalCatalogResponse
from app.schemas.rule_book_evaluate import (
    RuleBookEvaluateRequest,
    RuleBookEvaluateResponse,
)
from app.schemas.classification_api import (
    DocumentTypeRecognitionTestRequest,
    DocumentTypeRecognitionTestResponse,
)
from app.services.classification.document_type_sample_types import ParsedDocumentSample
from app.services.classification.document_type_sample_analyzer import (
    apply_sample_proposal_to_draft,
    compute_apply_ready,
    effective_proposal_signal_ids,
    parse_document_samples,
)
from app.services.classification.sample_proposal_engine import build_sample_proposal
from app.services.classification.document_type_recognition_service import evaluate_document_type_recognition
from app.services.classification.document_type_classify_preview import (
    classify_parsed_samples_for_proposal_preview,
    merge_draft_document_type,
)
from app.services.master_data.master_data_service import attach_masters_to_config_dict
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.classification.recognition_signal_registry import catalog_payload
from app.services.invoice.remap_service import remap_tenant_invoices_background
from app.services.rule_book.rule_book_config_io import (
    load_rule_book_config_dict,
    merge_persisted_rule_book_slices,
)
from app.services.rule_book.rule_book_evaluate_service import evaluate_rule_book
from app.services.rule_book.rule_book_ingest_stats import (
    attach_email_capture_ingest_stats,
    strip_email_capture_volatile_stats,
)
from app.services.rule_book.rule_book_save_buffer import (
    flush_rule_book_save_buffer,
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

    return await attach_email_capture_ingest_stats(
        db,
        tenant_id,
        await attach_masters_to_config_dict(db, tenant_id, data),
    )


async def _load_rule_book_document_types_only(
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
    return {"document_types": data.get("document_types") or []}


@router.get("/config", response_model=ApiEnvelope[dict[str, Any]])
async def get_rule_book_config(
    fields: str | None = Query(None, description="Optional slice, e.g. document_types"),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Return the rule book config for the current organisation."""
    if fields and fields.strip() == "document_types":
        return ApiEnvelope(data=await _load_rule_book_document_types_only(db, ctx.tenant_id))
    return ApiEnvelope(data=await _load_rule_book_response_dict(db, ctx.tenant_id))


@router.get("/recognition-signals", response_model=ApiEnvelope[RecognitionSignalCatalogResponse])
async def get_recognition_signal_catalog(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[RecognitionSignalCatalogResponse]:
    """Return the platform recognition signal registry for Rule Book UI."""
    _ = ctx
    return ApiEnvelope(data=RecognitionSignalCatalogResponse.model_validate(catalog_payload()))


@router.put("/config", response_model=ApiEnvelope[dict[str, Any]])
async def put_rule_book_config(
    body: RuleBookRulesPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Persist rule book changes; remap invoices in the background."""
    require_privilege(ctx, "Edit Policy")
    await load_rule_book_config_dict(db, ctx.tenant_id)

    try:
        raw = body.model_dump()
        raw["vendor_masters"] = []
        raw["employee_masters"] = []
        strip_email_capture_volatile_stats(raw)
        raw = await merge_persisted_rule_book_slices(db, ctx.tenant_id, raw)
        from app.services.classification.document_type_lifecycle import scrub_document_type_references

        payload = scrub_document_type_references(validate_rule_book_config_for_save(raw))
    except (RuleBookPostToValidationError, RuleBookDocumentTypeInvariantError) as exc:
        raise HTTPException(422, str(exc)) from exc
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
        remap_invoices=False,
    )
    background_tasks.add_task(
        remap_tenant_invoices_background,
        ctx.tenant_id,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )

    data = await _load_rule_book_response_dict(db, ctx.tenant_id)
    return ApiEnvelope(data=data)


@router.delete("/document-types/{code}", response_model=ApiEnvelope[dict[str, Any]])
async def delete_document_type(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Remove a document type from the tenant catalogue and persist immediately."""
    require_privilege(ctx, "Edit Policy")

    from app.services.classification.document_type_lifecycle import remove_document_type_from_payload

    # Commit any buffered PUT first so delete runs on the latest tenant catalogue.
    await flush_rule_book_save_buffer(
        tenant_id=ctx.tenant_id,
        db=db,
        remap_invoices=False,
    )

    before_raw = await load_rule_book_config_dict(db, ctx.tenant_id)
    try:
        before_payload = validate_rule_book_config_payload(before_raw)
    except (RuleBookPostToValidationError, RuleBookDocumentTypeInvariantError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except (ValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc

    try:
        payload = remove_document_type_from_payload(before_payload, code)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    from app.services.classification.classification_learning_service import (
        normalize_learning_dt_code,
        purge_learning_events_for_document_type,
    )

    deleted_code = normalize_learning_dt_code(code)
    await purge_learning_events_for_document_type(
        db,
        tenant_id=ctx.tenant_id,
        document_type_code=deleted_code,
    )

    after_raw = payload.model_dump()
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None

    from app.services.rule_book.rule_book_save_buffer import PendingRuleBookSave, commit_rule_book_save

    pending = PendingRuleBookSave(
        tenant_id=ctx.tenant_id,
        payload=payload,
        after_raw=after_raw,
        before_raw=before_raw,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await commit_rule_book_save(pending, db=db, remap_invoices=False)
    await db.commit()

    background_tasks.add_task(
        remap_tenant_invoices_background,
        ctx.tenant_id,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
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
    raw = await merge_persisted_rule_book_slices(db, tenant_id, raw)
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
    """Parse sample PDFs/images and propose document-type settings (Azure DI + OCR)."""
    require_privilege(ctx, "Edit Policy")
    if not files:
        raise HTTPException(400, "At least one sample file is required")
    if len(files) > _MAX_SAMPLE_FILES:
        raise HTTPException(400, f"At most {_MAX_SAMPLE_FILES} sample files allowed")

    uploads: list[tuple[str, bytes]] = []
    for upload in files:
        uploads.append(await _read_sample_upload(upload))

    def _parse_and_propose() -> tuple[DocumentTypeSampleProposal, list[ParsedDocumentSample]]:
        parsed_samples, parse_notes = parse_document_samples(uploads)
        return parsed_samples, parse_notes

    try:
        parsed_samples, parse_notes = await asyncio.to_thread(_parse_and_propose)
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

    catalogue = config.document_types if config is not None else []

    def _build_proposal() -> DocumentTypeSampleProposal:
        return build_sample_proposal(
            parsed_samples,
            catalogue=catalogue,
            purchase_bundle_role=purchase_bundle_role,
            parse_notes=parse_notes,
        )

    try:
        proposal = await asyncio.to_thread(_build_proposal)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    has_catalogue_preview = False
    if config is not None:
        has_catalogue_preview = True
        catalogue = merge_draft_document_type(config.document_types, draft_type)
        preview_catalogue = catalogue
        proposed_draft = draft_type
        preview_signals = effective_proposal_signal_ids(proposal)
        if draft_type is not None and preview_signals:
            proposed_draft = apply_sample_proposal_to_draft(
                draft_type,
                proposal,
                for_preview=True,
            )
            preview_catalogue = merge_draft_document_type(
                config.document_types,
                proposed_draft,
            )
        expected = expected_document_type_code.strip() or (
            draft_type.code.strip() if draft_type else ""
        )
        if proposed_draft is not None and preview_signals and expected:
            profile_signals_by_filename = {
                row.filename: frozenset(row.recognition_signals)
                for row in proposal.samples
            }
            previews = classify_parsed_samples_for_proposal_preview(
                parsed_samples,
                document_types=preview_catalogue,
                proposed_draft=proposed_draft,
                unclassified=config.document_classification,
                expected_code=expected,
                profile_signals_by_filename=profile_signals_by_filename,
            )
        else:
            from app.services.classification.document_type_classify_preview import (
                classify_parsed_samples_against_catalog,
            )

            previews = classify_parsed_samples_against_catalog(
                parsed_samples,
                document_types=preview_catalogue,
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
                "Proposed classifier does not match: "
                + ", ".join(mismatched)
                + ". Upload clearer samples or adjust identity signals before applying."
            )

    apply_ready, apply_block_reason = compute_apply_ready(
        proposal,
        has_catalogue_preview=has_catalogue_preview,
    )
    proposal = proposal.model_copy(
        update={
            "apply_ready": apply_ready,
            "apply_block_reason": apply_block_reason,
        }
    )

    return ApiEnvelope(data=proposal)


@router.post(
    "/document-types/test-recognition",
    response_model=ApiEnvelope[DocumentTypeRecognitionTestResponse],
)
async def test_document_type_recognition_endpoint(
    body: DocumentTypeRecognitionTestRequest,
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DocumentTypeRecognitionTestResponse]:
    """Test draft match/exclude rules against pasted OCR text."""
    require_privilege(ctx, "Edit Policy")
    try:
        draft = DocumentTypeDefinition.model_validate(body.draft_document_type)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid draft document type: {exc}") from exc

    result = evaluate_document_type_recognition(
        draft,
        document_text=body.document_text,
        document_heading=body.document_heading,
        email_sender=body.email_sender,
        attachment_name=body.attachment_name,
    )
    return ApiEnvelope(
        data=DocumentTypeRecognitionTestResponse(
            matches=result.matches,
            match_rules_passed=result.match_rules_passed,
            exclude_rules_passed=result.exclude_rules_passed,
            summary=result.summary,
            classifier_enabled=result.classifier_enabled,
        )
    )


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
    except (RuleBookPostToValidationError, RuleBookDocumentTypeInvariantError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except (ValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc


@router.get("/ai-providers")
async def list_ai_providers(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, object]]:
    """Availability of document AI providers for Rule Book settings."""
    from app.config import get_settings
    from app.services.extraction.document_intelligence import is_di_enabled

    settings = get_settings()
    azure_available = bool(is_di_enabled() and settings.runtime_llm_available)
    gemini_available = settings.gemini_vision_available
    foundry_available = settings.azure_foundry_vision_available
    claude_available = settings.claude_vision_available
    return ApiEnvelope(
        data={
            "azure_di": {
                "available": azure_available,
                "label": "Azure Document Intelligence",
                **(
                    {"reason": "Azure DI or runtime LLM not configured"}
                    if not azure_available
                    else {}
                ),
            },
            "azure_foundry_vision": {
                "available": foundry_available,
                "label": "Azure AI Foundry (GPT-4o Vision)",
                **(
                    {"reason": "AZURE_AI_FOUNDRY_* not configured"}
                    if not foundry_available
                    else {}
                ),
            },
            "claude_vision": {
                "available": claude_available,
                "label": "Claude Vision (Azure AI Foundry)",
                **(
                    {"reason": "AZURE_AI_VISUALIZATION_* not configured"}
                    if not claude_available
                    else {}
                ),
            },
            "gemini_vision": {
                "available": gemini_available,
                "label": "Gemini 2.5 Vision",
                **(
                    {"reason": "GEMINI_API_KEY not configured"}
                    if not gemini_available
                    else {}
                ),
            },
        }
    )
