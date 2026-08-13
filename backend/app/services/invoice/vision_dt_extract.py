"""DT-scoped vision field extract for the understood path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.services.extraction.document_ai_provider import DocumentAiProvider

logger = get_logger(__name__)


@dataclass(frozen=True)
class VisionDtExtractResult:
    success: bool
    needs_review: bool = False
    selected_keys: tuple[str, ...] = ()
    confidence: float = 0.0
    fail_reason: str | None = None
    provider: str = ""
    page_count: int = 0
    line_items_count: int = 0
    line_items_fallback: str | None = None


def vision_dt_extract_audit_detail(result: VisionDtExtractResult) -> dict:
    return {
        "success": result.success,
        "needs_review": result.needs_review,
        "selected_keys": list(result.selected_keys),
        "confidence": result.confidence,
        "fail_reason": result.fail_reason,
        "provider": result.provider,
        "page_count": result.page_count,
        "line_items_count": result.line_items_count,
        "line_items_fallback": result.line_items_fallback,
    }


def _minimal_vision_ocr(*, page_count: int = 0) -> OcrArtifact:
    """Sparse OCR stub so vision clients attach page images for extract."""
    return OcrArtifact(
        success=True,
        sparse=True,
        text="",
        text_length=0,
        di_model="vision_dt_scoped",
        payload_json={"provider": "vision_dt_scoped", "page_count": page_count},
    )


async def evaluate_vision_dt_extract(
    session: AsyncSession,
    invoice: Invoice,
    *,
    org: OrgContext,
    document_types: list[DocumentTypeDefinition],
    confirmed_dt: str,
    doc_provider: DocumentAiProvider,
    vision_page_images: list[bytes] | None = None,
    few_shots: list | None = None,
    definition: DocumentTypeDefinition | None = None,
) -> VisionDtExtractResult:
    """Extract fields listed on the mapped DT using vision page images."""
    from app.services.classification.document_type_catalog import get_document_type_definition
    from app.services.extraction.document_ai_provider import extract_fields
    from app.services.extraction.extraction_field_values import (
        effective_extraction_field_keys_for_dt,
        non_canonical_extraction_keys,
    )
    from app.services.extraction.llm_document_service import llm_result_to_invoice_data
    from app.services.invoice.vision_header_extract import CANONICAL_DOCUMENT_TYPE_KEY
    from app.services.invoice.vision_posting_continue import vision_header_ok_from_invoice
    from app.services.shared.file_storage import open_pdf_for_reading

    provider_token = doc_provider.value
    dt_token = (confirmed_dt or "").strip().upper()
    if not dt_token:
        return VisionDtExtractResult(
            success=False,
            fail_reason="no_document_type",
            provider=provider_token,
        )

    selected_keys = tuple(
        effective_extraction_field_keys_for_dt(document_types, dt_token) or ()
    )
    identity_keys = ("document_heading", CANONICAL_DOCUMENT_TYPE_KEY, "perspective")
    merged_keys = list(dict.fromkeys([*selected_keys, *identity_keys]))

    prior_heading = (invoice.document_heading or "").strip()
    prior_fields = (
        dict(invoice.extracted_fields) if isinstance(invoice.extracted_fields, dict) else {}
    )
    prior_canonical = str(prior_fields.get(CANONICAL_DOCUMENT_TYPE_KEY) or "").strip()
    prior_perspective = str(
        prior_fields.get("perspective") or prior_fields.get("llm_perspective") or ""
    ).strip()

    page_hint = len(vision_page_images or [])
    line_items_count = 0
    line_items_fallback: str | None = None
    wants_line_items = "line_items" in {str(k).strip().lower() for k in merged_keys}
    try:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            ocr = _minimal_vision_ocr(page_count=page_hint)
            extract_result = await extract_fields(
                ocr,
                file_path=path,
                org=org,
                document_types=document_types,
                confirmed_dt=dt_token,
                few_shots=few_shots,
                provider=doc_provider,
                vision_page_images=vision_page_images,
                prefer_vision_images=True,
            )
            ocr = extract_result.ocr
            llm_result = extract_result.llm

            if llm_result is None:
                return VisionDtExtractResult(
                    success=False,
                    selected_keys=tuple(merged_keys),
                    fail_reason="empty_llm_result",
                    provider=provider_token,
                    page_count=page_hint,
                )

            custom_keys = non_canonical_extraction_keys(merged_keys)
            try:
                parsed = llm_result_to_invoice_data(
                    llm_result,
                    ocr=ocr,
                    selected_keys=merged_keys,
                    custom_keys=custom_keys,
                    org=org,
                )
            except Exception as exc:
                logger.warning("vision_dt_extract_parse_failed", error=str(exc), dt=dt_token)
                return VisionDtExtractResult(
                    success=False,
                    selected_keys=tuple(merged_keys),
                    fail_reason="parse_failed",
                    provider=provider_token,
                    page_count=page_hint,
                )

            # Party/finance harvest often returns seller_*/buyer_*/billing_address even when
            # those keys are not on the DT — keep only configured (+ identity) keys.
            from app.services.extraction.extraction_field_values import filter_parsed_to_requested_keys

            parsed = filter_parsed_to_requested_keys(parsed, merged_keys)

            # Harvested extracted_fields often hold values when InvoiceData scalars are empty
            # (party/finance path with sparse OCR). Promote them before column persist.
            _hydrate_parsed_scalars_from_extracted(parsed)

            wants_line_items = "line_items" in {
                str(k).strip().lower() for k in merged_keys
            }
            if wants_line_items and not parsed.line_items:
                from app.services.extraction.line_items_fallback_service import (
                    apply_line_items_fallback,
                )

                # Prefer LLM document_text when vision OCR stub has empty text.
                ocr_blob = (getattr(ocr, "text", None) or "").strip() or (
                    parsed.document_text or ""
                )
                ocr_payload = dict(getattr(ocr, "payload_json", None) or {})
                if not ocr_payload.get("provider"):
                    ocr_payload["provider"] = "vision_dt_scoped"
                # Header total may sit on invoice when LLM left scalar empty.
                if parsed.total is None and getattr(invoice, "total", None) is not None:
                    parsed.total = invoice.total
                parsed, line_items_fallback = apply_line_items_fallback(
                    parsed,
                    ocr_text=ocr_blob,
                    ocr_payload=ocr_payload,
                    dt_definition=definition
                    or get_document_type_definition(
                        dt_token,
                        document_types=document_types,
                        tenant_id=invoice.tenant_id,
                    ),
                    pdf_path=path,
                    require_lines=True,
                )

            # Understood DT-scoped path previously skipped Field Translation —
            # Burmese/other non-English headings stayed untranslated. Run here
            # before persist so English lands in columns + extracted_fields.
            from app.services.audit.audit_service import log_event
            from app.services.extraction.field_translation_service import (
                apply_field_translation,
            )

            translation_ctx = (
                (parsed.document_text or "").strip()
                or str((parsed.extracted_fields or {}).get("document_summary") or "").strip()
                or (parsed.document_heading or "")
            )
            parsed, translation_detail = await apply_field_translation(
                parsed,
                context_text=translation_ctx,
                path="understood_dt",
            )
            if translation_detail.get("field_translation_attempted") or translation_detail.get(
                "field_translation_applied"
            ):
                await log_event(
                    session,
                    "field_translation",
                    invoice_id=invoice.id,
                    detail=translation_detail,
                )

            from app.schemas.rule_book_config import RuleBookConfigPayload
            from app.services.invoice.due_date_defaults import apply_due_on_receipt_to_parsed
            from app.services.invoice.pipeline import _apply_parsed_to_invoice

            dt_defn = definition or get_document_type_definition(
                dt_token,
                document_types=document_types,
                tenant_id=invoice.tenant_id,
            )
            apply_due_on_receipt_to_parsed(parsed, dt_defn)

            config = RuleBookConfigPayload(document_types=list(document_types))
            from app.services.approval.approval_pipeline_service import payable_fields_complete

            # Never overwrite clerk-completed vendor/total/dates with a weaker re-extract.
            preserve = payable_fields_complete(invoice)
            await _apply_parsed_to_invoice(
                session,
                invoice=invoice,
                loaded=invoice,
                parsed=parsed,
                config=config,
                preserve_existing=preserve,
                org=org,
            )
            line_items_count = len(parsed.line_items or [])
            # Safety net: DT requires lines + printed total, but every tier left
            # the grid empty (common on handwritten non-Latin receipts).
            if wants_line_items and line_items_count == 0:
                from dataclasses import replace as dc_replace

                from app.services.extraction.line_items_fallback_service import (
                    FALLBACK_HEADER,
                )
                from app.services.invoice.invoice_data import ParsedLineItem
                from app.services.invoice.pipeline import _replace_line_items
                from app.services.shared.amount_sanity import plausible_money

                rescue_total = plausible_money(parsed.total) or plausible_money(
                    getattr(invoice, "total", None)
                )
                if rescue_total is not None and rescue_total > 0:
                    heading = (
                        (parsed.document_heading or "").strip()
                        or (invoice.document_heading or "").strip()
                        or None
                    )
                    rescue_rows = [
                        ParsedLineItem(
                            description=heading[:200] if heading else None,
                            amount=rescue_total,
                            source=FALLBACK_HEADER,
                        )
                    ]
                    parsed = dc_replace(parsed, line_items=rescue_rows)
                    await _replace_line_items(session, invoice, rescue_rows)
                    line_items_count = 1
                    line_items_fallback = FALLBACK_HEADER
            # Ensure column due_date is set even if scalar apply skipped empties oddly.
            from app.services.invoice.due_date_defaults import apply_due_on_receipt_to_invoice

            apply_due_on_receipt_to_invoice(invoice, dt_defn)
            # Employee name comes from Employee Master via mail sender — not OCR/LLM.
            from app.services.purchase.team_expense_service import (
                stamp_team_expense_employee_identity,
            )

            await stamp_team_expense_employee_identity(session, invoice)
    except Exception as exc:
        logger.warning("vision_dt_extract_failed", error=str(exc), dt=dt_token)
        return VisionDtExtractResult(
            success=False,
            selected_keys=tuple(merged_keys),
            fail_reason="provider_error",
            provider=provider_token,
            page_count=page_hint,
        )

    if prior_heading and not (invoice.document_heading or "").strip():
        invoice.document_heading = prior_heading
    fields = dict(invoice.extracted_fields or {})
    # Restore type-suggest / identity meta that must survive DT-scoped field persist.
    for meta_key in (
        CANONICAL_DOCUMENT_TYPE_KEY,
        "perspective",
        "llm_perspective",
        "document_summary",
        "document_role_hints",
        "vision_type_suggest_confidence",
        "document_heading",
    ):
        prior_val = prior_fields.get(meta_key)
        if prior_val is not None and str(prior_val).strip() and not str(fields.get(meta_key) or "").strip():
            fields[meta_key] = prior_val
    if prior_canonical and not str(fields.get(CANONICAL_DOCUMENT_TYPE_KEY) or "").strip():
        fields[CANONICAL_DOCUMENT_TYPE_KEY] = prior_canonical
    if prior_perspective and not str(fields.get("perspective") or "").strip():
        fields["perspective"] = prior_perspective
        fields["llm_perspective"] = prior_perspective
    if prior_heading and not str(fields.get("document_heading") or "").strip():
        fields["document_heading"] = prior_heading

    # Drop unconfigured harvest keys (party extras) while keeping DT + meta.
    allowed = {str(k).strip().lower() for k in merged_keys}
    allowed.update(
        {
            "document_summary",
            "document_role_hints",
            "vision_type_suggest_confidence",
            "vision_bundle_key",
            "vision_bundle_kind",
            "vision_bundle_custom_field",
            "llm_perspective",
            "field_confidence",
            # Field Translation Agent originals / audit (must survive DT filter).
            "original_document_heading",
            "line_item_description_originals",
            "translation_source_language",
            "translation_applied",
            "translation_confidence",
            "translation_skip_reason",
        }
    )
    fields = {
        k: v
        for k, v in fields.items()
        if (
            str(k).strip().lower() in allowed
            or str(k).strip().lower().startswith("original_")
            or str(k).strip().lower().startswith("translation_")
        )
    }
    invoice.extracted_fields = fields or None

    confidence = float(getattr(llm_result, "confidence", 0.0) or 0.0)
    defn = definition or get_document_type_definition(
        dt_token,
        document_types=document_types,
        tenant_id=invoice.tenant_id,
    )
    needs_review = not vision_header_ok_from_invoice(invoice, defn)
    from app.services.extraction.line_item_extraction_policy import (
        team_expense_hard_requires_line_items,
    )

    hard_wants_lines = team_expense_hard_requires_line_items(
        defn,
        team_expense_kind=getattr(invoice, "team_expense_kind", None),
    )
    line_items_incomplete = bool(hard_wants_lines) and line_items_count == 0
    if line_items_incomplete:
        needs_review = True
        from app.services.invoice.invoice_evaluation_service import EVAL_LINE_ITEMS_REVIEW

        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_LINE_ITEMS_REVIEW

    return VisionDtExtractResult(
        success=True,
        needs_review=needs_review,
        selected_keys=tuple(merged_keys),
        confidence=confidence,
        provider=provider_token,
        page_count=page_hint,
        line_items_count=line_items_count,
        line_items_fallback=line_items_fallback,
    )


def _hydrate_parsed_scalars_from_extracted(parsed) -> None:
    """Fill empty InvoiceData scalars from harvested extracted_fields."""
    from datetime import date, datetime
    from decimal import Decimal, InvalidOperation

    extracted = parsed.extracted_fields if isinstance(parsed.extracted_fields, dict) else {}
    if not extracted:
        return

    def _s(key: str) -> str:
        return str(extracted.get(key) or "").strip()

    if not (parsed.vendor or "").strip():
        parsed.vendor = _s("vendor") or _s("seller_name") or None
    if not (parsed.invoice_no or "").strip():
        parsed.invoice_no = _s("invoice_no") or None
    if not (parsed.po_reference or "").strip():
        parsed.po_reference = _s("po_reference") or None
    if not (parsed.currency or "").strip():
        parsed.currency = _s("currency")
    if parsed.invoice_date is None and _s("invoice_date"):
        raw = _s("invoice_date")
        try:
            parsed.invoice_date = date.fromisoformat(raw[:10])
        except ValueError:
            try:
                parsed.invoice_date = datetime.fromisoformat(raw).date()
            except ValueError:
                pass
    if parsed.due_date is None and _s("due_date"):
        raw = _s("due_date")
        try:
            parsed.due_date = date.fromisoformat(raw[:10])
        except ValueError:
            try:
                parsed.due_date = datetime.fromisoformat(raw).date()
            except ValueError:
                pass

    def _money(key: str):
        raw = _s(key)
        if not raw:
            return None
        try:
            return Decimal(raw.replace(",", ""))
        except (InvalidOperation, ValueError):
            return None

    if parsed.subtotal is None:
        parsed.subtotal = _money("subtotal")
    if parsed.gst is None:
        parsed.gst = _money("gst")
    if parsed.total is None:
        parsed.total = _money("total")
    if not (parsed.document_heading or "").strip():
        parsed.document_heading = _s("document_heading") or None
