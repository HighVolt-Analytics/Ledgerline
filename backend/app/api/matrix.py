"""Document matrix — pipeline stages from server-side audit + status."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.schemas.matrix_api import MatrixListRequest
from app.schemas.pipeline import MatrixRowResponse
from app.services.reports.matrix_service import fetch_document_matrix

router = APIRouter(prefix="/matrix", tags=["matrix"])


@router.get("", response_model=ApiEnvelope[list[MatrixRowResponse]])
async def document_matrix(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[str | None, Query()] = None,
    route_target: Annotated[
        str | None, Query(description="Filter by rule book route target")
    ] = None,
    evaluation_status: Annotated[
        str | None, Query(description="Filter by evaluation status")
    ] = None,
    capture_source: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    matrix_filter: Annotated[str | None, Query()] = None,
    approval_board_column: Annotated[
        str | None, Query(description="Filter by approvals board column")
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[MatrixRowResponse]]:
    """Invoices with server-computed pipeline stage cells, flags, and payment readiness."""
    params = MatrixListRequest(
        page=page,
        page_size=page_size,
        status=status,
        route_target=route_target,
        evaluation_status=evaluation_status,
        capture_source=capture_source,
        q=q,
        matrix_filter=matrix_filter,
        approval_board_column=approval_board_column,
    )
    result = await fetch_document_matrix(db, tenant_id=ctx.tenant_id, params=params)
    return ApiEnvelope(
        data=result.rows,
        meta=ResponseMeta(
            page=result.page,
            total=result.total,
            pages=result.pages,
            matrix_document_count=result.document_count,
            matrix_flagged=result.flagged,
            matrix_duplicates=result.duplicates,
            matrix_awaiting=result.awaiting,
            matrix_paid_this_month=result.paid_this_month,
            approval_review_count=result.review_count,
            approval_processing_count=result.processing_count,
            approval_approved_count=result.approved_count,
            approval_rejected_count=result.rejected_count,
        ),
    )
