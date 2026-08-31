"""Bank feed / cash reconciliation HTTP API (Phase 2: accounts + CSV import + list)."""

from __future__ import annotations

import math
from datetime import date

from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.models.audit import AuditLog
from app.models.bank_feed import BankTransaction, BankTxnDirection
from app.schemas.audit import AuditLogResponse
from app.schemas.bank_feed import (
    BankAccountCreate,
    BankAccountResponse,
    BankCreateRequest,
    BankFeedImportListResponse,
    BankFeedImportResponse,
    BankMatchTargetResponse,
    BankTransactionListResponse,
    BankTransactionMatchResponse,
    BankTransactionNoteResponse,
    BankTransactionResponse,
    BankTransferRequest,
    CategorizeRunItemResponse,
    CategorizeRunResponse,
    CreateBankTransactionNoteRequest,
    ExcludeTransactionRequest,
    ManualMatchRequest,
    MatchRunItemResponse,
    MatchRunResponse,
    SetCategoryRequest,
    UnmatchRequest,
)
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.services.audit.audit_service import log_event
from app.services.auth.privilege_service import require_privilege
from app.services.bank_feeds import (
    account_service,
    categorize_service,
    create_service,
    import_service,
    match_service,
    match_targets,
    transaction_service,
    transfer_service,
)
from app.services.bank_feeds.create_service import BankCreateConflict, BankCreateError
from app.services.payments.fiscal_period_service import PeriodClosedError
from app.services.bank_feeds.reference import resolve_txn_reference

router = APIRouter(prefix="/bank-feeds", tags=["bank-feeds"])

_MAX_CSV_BYTES = 10 * 1024 * 1024


def _money_flow(direction: str) -> str:
    if direction == BankTxnDirection.CREDIT.value:
        return "in"
    return "out"


def _possible_duplicate_of(txn: BankTransaction) -> list[int] | None:
    flags = txn.review_flags if isinstance(txn.review_flags, dict) else None
    if not flags:
        return None
    raw = flags.get("possible_duplicate_of")
    if not isinstance(raw, list):
        return None
    out: list[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out or None


def _categorization_fields(txn: BankTransaction) -> dict:
    flags = txn.review_flags if isinstance(txn.review_flags, dict) else {}
    cat = flags.get("categorization") if isinstance(flags.get("categorization"), dict) else None
    if not cat or not txn.category_coa:
        return {
            "category_source": None,
            "category_rule_name": None,
            "category_matched_snippet": None,
        }
    source = cat.get("source")
    return {
        "category_source": source if source in ("rule", "manual") else None,
        "category_rule_name": cat.get("rule_name"),
        "category_matched_snippet": cat.get("matched_snippet"),
    }


def _txn_response(
    txn: BankTransaction,
    *,
    matches: list | None = None,
) -> BankTransactionResponse:
    return BankTransactionResponse(
        id=txn.id,
        bank_account_id=txn.bank_account_id,
        import_id=txn.import_id,
        txn_date=txn.txn_date,
        posted_date=txn.posted_date,
        description=txn.description,
        amount=float(txn.amount),
        currency=txn.currency,
        money_flow=_money_flow(txn.direction),
        balance=float(txn.balance) if txn.balance is not None else None,
        reference=resolve_txn_reference(txn),
        match_status=txn.match_status,
        category_coa=txn.category_coa,
        **_categorization_fields(txn),
        possible_duplicate_of=_possible_duplicate_of(txn),
        posted_journal_batch_id=txn.posted_journal_batch_id,
        created_at=txn.created_at,
        updated_at=txn.updated_at,
        matches=list(matches or []),
    )


async def _txn_response_enriched(
    db: AsyncSession,
    *,
    tenant_id,
    txn: BankTransaction,
    matches: list | None = None,
) -> BankTransactionResponse:
    enriched = await match_targets.matches_to_responses(
        db, tenant_id=tenant_id, matches=list(matches or [])
    )
    return _txn_response(txn, matches=enriched)


def _import_response(
    row,
    *,
    reused_existing: bool = False,
    categorized_count: int = 0,
) -> BankFeedImportResponse:
    report = row.error_report if isinstance(row.error_report, dict) else {}
    count = categorized_count
    if not count and isinstance(report, dict):
        raw = report.get("categorized_count")
        if isinstance(raw, int):
            count = raw
    return BankFeedImportResponse(
        id=row.id,
        bank_account_id=row.bank_account_id,
        source=row.source,
        filename=row.filename,
        file_sha256=row.file_sha256,
        status=row.status,
        row_count=row.row_count,
        accepted_count=row.accepted_count,
        duplicate_count=row.duplicate_count,
        error_count=row.error_count,
        categorized_count=count,
        error_report=row.error_report,
        actor_user_id=row.actor_user_id,
        imported_at=row.imported_at,
        reused_existing=reused_existing,
    )


@router.get("/accounts", response_model=ApiEnvelope[list[BankAccountResponse]])
async def list_accounts(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[BankAccountResponse]]:
    rows = await account_service.list_bank_accounts(
        db, tenant_id=ctx.tenant_id, include_archived=include_archived
    )
    return ApiEnvelope(data=[BankAccountResponse.model_validate(r) for r in rows])


@router.post("/accounts", response_model=ApiEnvelope[BankAccountResponse], status_code=201)
async def create_account(
    body: BankAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankAccountResponse]:
    require_privilege(ctx, "Post")
    currency = body.currency.strip().upper()
    if len(currency) != 3:
        raise HTTPException(400, "currency must be a 3-letter ISO code")
    row = await account_service.create_bank_account(
        db,
        tenant_id=ctx.tenant_id,
        name=body.name,
        currency=currency,
        account_mask=body.account_mask,
        coa_account_name=body.coa_account_name,
    )
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "bank_account_created",
        tenant_id=ctx.tenant_id,
        detail={
            "bank_account_id": row.id,
            "name": row.name,
            "currency": row.currency,
            "coa_account_code": row.coa_account_code,
            "coa_account_name": row.coa_account_name,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=request.client.host if request.client else None,
    )
    await db.commit()
    return ApiEnvelope(data=BankAccountResponse.model_validate(row))


@router.post(
    "/accounts/{account_id}/imports",
    response_model=ApiEnvelope[BankFeedImportResponse],
)
async def upload_csv_import(
    account_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankFeedImportResponse]:
    require_privilege(ctx, "Post")
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(400, "CSV exceeds 10 MB limit")

    actor_name, actor_email = await actor_from_context(db, ctx)
    result = await import_service.import_canonical_csv(
        db,
        tenant_id=ctx.tenant_id,
        account=account,
        content=raw,
        filename=file.filename,
        actor_user_id=ctx.user_id,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=request.client.host if request.client else None,
    )
    await db.commit()
    return ApiEnvelope(
        data=_import_response(
            result.import_row,
            reused_existing=result.reused_existing,
            categorized_count=result.categorized_count,
        )
    )


@router.get("/imports/{import_id}", response_model=ApiEnvelope[BankFeedImportResponse])
async def get_import(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankFeedImportResponse]:
    row = await transaction_service.get_import(
        db, tenant_id=ctx.tenant_id, import_id=import_id
    )
    if row is None:
        raise HTTPException(404, "Import not found")
    return ApiEnvelope(data=_import_response(row))


@router.get(
    "/accounts/{account_id}/imports",
    response_model=ApiEnvelope[BankFeedImportListResponse],
)
async def list_account_imports(
    account_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankFeedImportListResponse]:
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")
    rows, total = await transaction_service.list_imports(
        db,
        tenant_id=ctx.tenant_id,
        bank_account_id=account_id,
        page=page,
        page_size=page_size,
    )
    pages = max(1, int(math.ceil(total / page_size))) if total else 1
    return ApiEnvelope(
        data=BankFeedImportListResponse(
            items=[_import_response(r) for r in rows]
        ),
        meta=ResponseMeta(page=page, total=total, pages=pages),
    )


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=ApiEnvelope[BankTransactionListResponse],
)
async def list_account_transactions(
    account_id: int,
    match_status: str | None = Query(None),
    reconcile: bool = Query(False),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionListResponse]:
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")

    rows, total = await transaction_service.list_transactions(
        db,
        tenant_id=ctx.tenant_id,
        bank_account_id=account_id,
        match_status=None if reconcile else match_status,
        reconcile=reconcile,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    pages = max(1, int(math.ceil(total / page_size))) if total else 1
    return ApiEnvelope(
        data=BankTransactionListResponse(items=[_txn_response(r) for r in rows]),
        meta=ResponseMeta(page=page, total=total, pages=pages),
    )


@router.get(
    "/transactions/{transaction_id}",
    response_model=ApiEnvelope[BankTransactionResponse],
)
async def get_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionResponse]:
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    matches = await transaction_service.list_matches_for_transaction(
        db, tenant_id=ctx.tenant_id, bank_transaction_id=txn.id
    )
    return ApiEnvelope(
        data=await _txn_response_enriched(
            db, tenant_id=ctx.tenant_id, txn=txn, matches=matches
        )
    )


@router.get(
    "/match-targets",
    response_model=ApiEnvelope[list[BankMatchTargetResponse]],
)
async def list_match_targets(
    matched_type: str = Query(..., pattern="^(payment|collection)$"),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[BankMatchTargetResponse]]:
    """Searchable payment/collection picker rows for manual match (no raw-ID UX)."""
    try:
        rows = await match_targets.search_match_targets(
            db,
            tenant_id=ctx.tenant_id,
            matched_type=matched_type,
            q=q,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=rows)


@router.get(
    "/transactions/{transaction_id}/audit",
    response_model=ApiEnvelope[list[AuditLogResponse]],
)
async def list_transaction_audit(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[AuditLogResponse]]:
    """Audit trail for one bank line (detail.bank_transaction_id via JSON containment)."""
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.tenant_id == ctx.tenant_id,
            AuditLog.detail.contains({"bank_transaction_id": transaction_id}),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(200)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return ApiEnvelope(data=[AuditLogResponse.model_validate(r) for r in rows])


@router.post(
    "/accounts/{account_id}/match-run",
    response_model=ApiEnvelope[MatchRunResponse],
)
async def run_account_match(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[MatchRunResponse]:
    require_privilege(ctx, "Post")
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    results = await match_service.run_match_for_account(
        db,
        tenant_id=ctx.tenant_id,
        account=account,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=request.client.host if request.client else None,
    )
    await db.commit()
    return ApiEnvelope(
        data=MatchRunResponse(
            items=[
                MatchRunItemResponse(
                    transaction_id=r.transaction_id,
                    status=r.status,
                    matches_written=r.matches_written,
                    auto_matched=r.auto_matched,
                    tie_demoted=r.tie_demoted,
                )
                for r in results
            ]
        )
    )


@router.post(
    "/accounts/{account_id}/categorize-run",
    response_model=ApiEnvelope[CategorizeRunResponse],
)
async def run_account_categorize(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CategorizeRunResponse]:
    require_privilege(ctx, "Post")
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    results = await categorize_service.run_categorize_for_account(
        db,
        tenant_id=ctx.tenant_id,
        account=account,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=request.client.host if request.client else None,
    )
    await db.commit()
    categorized_count = sum(1 for r in results if r.categorized)
    return ApiEnvelope(
        data=CategorizeRunResponse(
            categorized_count=categorized_count,
            items=[
                CategorizeRunItemResponse(
                    transaction_id=r.transaction_id,
                    categorized=r.categorized,
                    category_coa=r.category_coa,
                    rule_id=r.rule_id,
                    rule_name=r.rule_name,
                )
                for r in results
            ],
        )
    )


@router.patch(
    "/transactions/{transaction_id}/category",
    response_model=ApiEnvelope[BankTransactionResponse],
)
async def set_transaction_category(
    transaction_id: int,
    body: SetCategoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await categorize_service.set_manual_category(
            db,
            tenant_id=ctx.tenant_id,
            txn=txn,
            category_coa=body.category_coa,
            ledger=body.ledger,
            sub_ledger=body.sub_ledger,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    matches = await transaction_service.list_matches_for_transaction(
        db, tenant_id=ctx.tenant_id, bank_transaction_id=row.id
    )
    payload = await _txn_response_enriched(
        db, tenant_id=ctx.tenant_id, txn=row, matches=matches
    )
    await db.commit()
    return ApiEnvelope(data=payload)


@router.post(
    "/transactions/{transaction_id}/matches",
    response_model=ApiEnvelope[BankTransactionMatchResponse],
    status_code=201,
)
async def create_manual_match(
    transaction_id: int,
    body: ManualMatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionMatchResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=txn.bank_account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await match_service.create_manual_match(
            db,
            tenant_id=ctx.tenant_id,
            account=account,
            txn=txn,
            matched_type=body.matched_type,
            matched_id=body.matched_id,
            allocated_amount=(
                Decimal(str(body.allocated_amount))
                if body.allocated_amount is not None
                else None
            ),
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    payload = await match_targets.match_to_response(
        db, tenant_id=ctx.tenant_id, match=row
    )
    await db.commit()
    return ApiEnvelope(data=payload)


@router.post(
    "/matches/{match_id}/confirm",
    response_model=ApiEnvelope[BankTransactionMatchResponse],
)
async def confirm_match(
    match_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionMatchResponse]:
    require_privilege(ctx, "Post")
    match = await match_service.get_match(
        db, tenant_id=ctx.tenant_id, match_id=match_id
    )
    if match is None:
        raise HTTPException(404, "Match not found")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=match.bank_transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await match_service.confirm_suggested_match(
            db,
            tenant_id=ctx.tenant_id,
            match=match,
            txn=txn,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    payload = await match_targets.match_to_response(
        db, tenant_id=ctx.tenant_id, match=row
    )
    await db.commit()
    return ApiEnvelope(data=payload)


@router.post(
    "/matches/{match_id}/unmatch",
    response_model=ApiEnvelope[BankTransactionMatchResponse],
)
async def unmatch(
    match_id: int,
    request: Request,
    body: UnmatchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionMatchResponse]:
    require_privilege(ctx, "Post")
    match = await match_service.get_match(
        db, tenant_id=ctx.tenant_id, match_id=match_id
    )
    if match is None:
        raise HTTPException(404, "Match not found")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=match.bank_transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await match_service.unmatch(
            db,
            tenant_id=ctx.tenant_id,
            match=match,
            txn=txn,
            reason=body.reason if body else None,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    payload = await match_targets.match_to_response(
        db, tenant_id=ctx.tenant_id, match=row
    )
    await db.commit()
    return ApiEnvelope(data=payload)


@router.post(
    "/transactions/{transaction_id}/exclude",
    response_model=ApiEnvelope[BankTransactionResponse],
)
async def exclude_transaction(
    transaction_id: int,
    request: Request,
    body: ExcludeTransactionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await match_service.exclude_transaction(
            db,
            tenant_id=ctx.tenant_id,
            txn=txn,
            reason=body.reason if body else None,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    txn_id = row.id
    await db.commit()
    refreshed = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=txn_id
    )
    if refreshed is None:
        raise HTTPException(404, "Transaction not found")
    matches = await transaction_service.list_matches_for_transaction(
        db, tenant_id=ctx.tenant_id, bank_transaction_id=txn_id
    )
    return ApiEnvelope(
        data=await _txn_response_enriched(
            db, tenant_id=ctx.tenant_id, txn=refreshed, matches=matches
        )
    )


@router.post(
    "/transactions/{transaction_id}/create",
    response_model=ApiEnvelope[BankTransactionResponse],
)
async def create_from_bank_line(
    transaction_id: int,
    body: BankCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    account = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=txn.bank_account_id
    )
    if account is None:
        raise HTTPException(404, "Bank account not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    party_input = (
        create_service.BankCreatePartyInput(name=body.create_party.name)
        if body.create_party is not None
        else None
    )
    try:
        row = await create_service.create_bank_journal(
            db,
            tenant_id=ctx.tenant_id,
            txn=txn,
            account=account,
            party_type=body.party_type,
            party_id=body.party_id,
            create_party=party_input,
            ledger=body.ledger,
            description=body.description,
            tax_rate_percent=body.tax_rate_percent,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except PeriodClosedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except BankCreateConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except BankCreateError as exc:
        raise HTTPException(400, str(exc)) from exc
    matches = await transaction_service.list_matches_for_transaction(
        db, tenant_id=ctx.tenant_id, bank_transaction_id=row.id
    )
    payload = await _txn_response_enriched(
        db, tenant_id=ctx.tenant_id, txn=row, matches=matches
    )
    await db.commit()
    return ApiEnvelope(data=payload)


@router.post(
    "/transactions/{transaction_id}/transfer",
    response_model=ApiEnvelope[BankTransactionResponse],
)
async def transfer_bank_line(
    transaction_id: int,
    body: BankTransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    source = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=txn.bank_account_id
    )
    if source is None:
        raise HTTPException(404, "Bank account not found")
    destination = await account_service.get_bank_account(
        db, tenant_id=ctx.tenant_id, account_id=body.to_bank_account_id
    )
    if destination is None:
        raise HTTPException(404, "Destination account not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await transfer_service.transfer_between_accounts(
            db,
            tenant_id=ctx.tenant_id,
            txn=txn,
            source_account=source,
            destination_account=destination,
            description=body.description,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except PeriodClosedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except BankCreateConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except BankCreateError as exc:
        raise HTTPException(400, str(exc)) from exc
    matches = await transaction_service.list_matches_for_transaction(
        db, tenant_id=ctx.tenant_id, bank_transaction_id=row.id
    )
    payload = await _txn_response_enriched(
        db, tenant_id=ctx.tenant_id, txn=row, matches=matches
    )
    await db.commit()
    return ApiEnvelope(data=payload)


@router.get(
    "/transactions/{transaction_id}/notes",
    response_model=ApiEnvelope[list[BankTransactionNoteResponse]],
)
async def list_transaction_notes(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[BankTransactionNoteResponse]]:
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    rows = await transaction_service.list_notes(
        db,
        tenant_id=ctx.tenant_id,
        bank_transaction_id=transaction_id,
    )
    return ApiEnvelope(
        data=[BankTransactionNoteResponse.model_validate(r) for r in rows]
    )


@router.post(
    "/transactions/{transaction_id}/notes",
    response_model=ApiEnvelope[BankTransactionNoteResponse],
    status_code=201,
)
async def create_transaction_note(
    transaction_id: int,
    body: CreateBankTransactionNoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionNoteResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    try:
        row = await transaction_service.create_note(
            db,
            tenant_id=ctx.tenant_id,
            bank_transaction_id=transaction_id,
            body=body.body,
            author_user_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "bank_txn_note_added",
        tenant_id=ctx.tenant_id,
        detail={
            "bank_transaction_id": transaction_id,
            "note_id": row.id,
            "actor_user": actor_name,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=request.client.host if request.client else None,
    )
    await db.commit()
    return ApiEnvelope(data=BankTransactionNoteResponse.model_validate(row))


@router.post(
    "/transactions/{transaction_id}/reverse-create",
    response_model=ApiEnvelope[BankTransactionResponse],
)
async def reverse_bank_create(
    transaction_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BankTransactionResponse]:
    require_privilege(ctx, "Post")
    txn = await transaction_service.get_transaction(
        db, tenant_id=ctx.tenant_id, transaction_id=transaction_id
    )
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row = await transfer_service.reverse_bank_posting(
            db,
            tenant_id=ctx.tenant_id,
            txn=txn,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=request.client.host if request.client else None,
        )
    except PeriodClosedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except BankCreateConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except BankCreateError as exc:
        raise HTTPException(400, str(exc)) from exc
    matches = await transaction_service.list_matches_for_transaction(
        db, tenant_id=ctx.tenant_id, bank_transaction_id=row.id
    )
    payload = await _txn_response_enriched(
        db, tenant_id=ctx.tenant_id, txn=row, matches=matches
    )
    await db.commit()
    return ApiEnvelope(data=payload)
