from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request, http_not_found
from app.schemas.audit import AuditLogExportRequest, AuditLogListRequest, AuditLogResponse
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.services.audit.audit_log_service import build_audit_export, list_audit_logs

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=ApiEnvelope[list[AuditLogResponse]])
async def list_audit_log(
    params: Annotated[AuditLogListRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[AuditLogResponse]]:
    try:
        result = await list_audit_logs(db, tenant_id=ctx.tenant_id, params=params)
    except LookupError as exc:
        raise http_not_found(exc) from exc

    return ApiEnvelope(
        data=[AuditLogResponse.model_validate(r) for r in result.rows],
        meta=ResponseMeta(page=result.page, total=result.total, pages=result.pages),
    )


@router.get("/export")
async def export_audit_log_csv(
    params: Annotated[AuditLogExportRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download audit trail as CSV for the organisation."""
    try:
        payload = await build_audit_export(db, tenant_id=ctx.tenant_id, params=params)
    except ValueError as exc:
        raise http_bad_request(exc) from exc

    return Response(
        content=payload.csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )
