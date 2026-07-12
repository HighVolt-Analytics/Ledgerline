"""Per-route extraction strategy implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.document_intelligence import is_di_enabled
from app.services.extraction.extraction_orchestrator import invoice_data_to_payload_fields
from app.services.extraction.line_items_parser import serialize_line_items
from app.services.extraction.routing.decision import DocumentRouteDecision
from app.services.extraction.routing.routes import ExtractionRoute
from app.services.extraction.routing.strategy import (
    ExtractionStrategyConfig,
    StrategyEnrichResult,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "application/pdf"


def _base_audit(
    decision: DocumentRouteDecision,
    config: ExtractionStrategyConfig,
    *,
    attempted: bool,
    success: bool,
    failure_reason: str | None = None,
    skip_reason: str | None = None,
    di_model: str = "",
    fields_populated: list[str] | None = None,
    models_run: list[str] | None = None,
) -> dict[str, object]:
    return {
        "attempted": attempted,
        "success": success,
        "failure_reason": failure_reason,
        "skip_reason": skip_reason,
        "di_model": di_model,
        "fields_populated": fields_populated or [],
        "confirmed_dt": decision.confirmed_dt,
        "extraction_route": decision.route.value,
        "extraction_strategy": config.name,
        "models_run": models_run or [],
        "layout_line_mode": config.layout_line_mode,
        "review_hints": list(decision.review_hints),
        "route_reasons": list(decision.reasons),
    }


def _apply_semantic_enrich(
    ocr: OcrArtifact,
    invoice_data: Any,
    *,
    decision: DocumentRouteDecision,
    config: ExtractionStrategyConfig,
    model_id: str,
    models_run: list[str],
    raw_di: dict[str, object] | None = None,
) -> OcrArtifact:
    from app.services.extraction.extraction_field_values import attach_extraction_metadata_to_payload
    from app.services.extraction.finance_document_adapters import (
        attach_finance_document_to_payload,
    )

    settings = get_settings()
    text = ocr.text or ""
    if not text.strip() and getattr(invoice_data, "document_text", None):
        text = str(invoice_data.document_text).strip()

    layout_kv = dict(ocr.layout_kv)
    payload = dict(ocr.payload_json or {})
    fields = invoice_data_to_payload_fields(invoice_data)
    # Neutral key for multi-doc; keep invoice_fields as compatibility alias
    payload["semantic_fields"] = fields
    payload["invoice_fields"] = fields
    if invoice_data.line_items:
        payload["di_line_items"] = serialize_line_items(invoice_data.line_items)

    attach_extraction_metadata_to_payload(
        payload,
        invoice_data,
        decision=decision,
        strategy_name=config.name,
        models_run=models_run,
        layout_line_mode=config.layout_line_mode,
    )
    if raw_di is not None:
        payload["raw_di"] = raw_di

    payload["di_model"] = model_id
    payload["provider"] = "azure_di"
    attach_finance_document_to_payload(
        payload,
        invoice_data,
        decision=decision,
        source_model=model_id,
    )

    text_length = len(text)
    sparse = text_length < settings.ocr_min_text_chars
    return OcrArtifact(
        success=True,
        sparse=sparse,
        text=text,
        text_length=text_length,
        di_model=model_id,
        layout_kv=layout_kv,
        payload_json=payload,
    )


def _tag_layout_only(
    ocr: OcrArtifact,
    decision: DocumentRouteDecision,
    config: ExtractionStrategyConfig,
    *,
    skip_reason: str | None = None,
) -> OcrArtifact:
    from app.services.extraction.finance_document_adapters import (
        attach_finance_document_to_payload,
        invoice_data_from_layout_payload,
    )

    payload = dict(ocr.payload_json or {})
    payload["extraction_route"] = decision.route.value
    payload["extraction_strategy"] = config.name
    payload["layout_line_mode"] = config.layout_line_mode
    payload["di_models_run"] = list(payload.get("di_models_run") or [])
    if decision.review_hints:
        payload["review_hints"] = list(decision.review_hints)
    if skip_reason:
        payload["skip_reason"] = skip_reason
        payload["fallback_reason"] = skip_reason

    layout_data = invoice_data_from_layout_payload(
        payload,
        text=ocr.text or "",
        layout_kv=dict(ocr.layout_kv),
    )
    sources = dict(layout_data.raw_fields.get("field_sources") or {})
    conf = dict(layout_data.raw_fields.get("field_confidence") or {})
    # Preserve existing classify-time layout KV sources
    for key in (ocr.layout_kv or {}):
        sources.setdefault(key, "layout_kv")
        conf.setdefault(key, None)
    if payload.get("table_line_items") or layout_data.line_items:
        sources.setdefault("line_items", "layout_table")
        conf.setdefault("line_items", conf.get("line_items"))
    payload["field_sources"] = sources
    payload["field_confidence"] = conf
    layout_data.raw_fields["field_sources"] = sources
    layout_data.raw_fields["field_confidence"] = conf

    source_model = ocr.di_model or (config.primary_model or "prebuilt-layout")
    attach_finance_document_to_payload(
        payload,
        layout_data,
        decision=decision,
        source_model=source_model,
    )

    return OcrArtifact(
        success=ocr.success,
        sparse=ocr.sparse,
        text=ocr.text,
        text_length=ocr.text_length,
        di_model=ocr.di_model or source_model,
        layout_kv=dict(ocr.layout_kv),
        payload_json=payload,
        error=ocr.error,
    )


class InvoiceFamilyStrategy:
    """prebuilt-invoice primary; layout gap-fill for line items only."""

    def __init__(self, route: ExtractionRoute) -> None:
        settings = get_settings()
        self.route = route
        self.config = ExtractionStrategyConfig(
            name="invoice_family",
            primary_model=settings.azure_di_model_id or "prebuilt-invoice",
            fallback_models=(settings.azure_di_layout_model_id or "prebuilt-layout",),
            expect_line_items=True,
            totals_authoritative=True,
            layout_line_mode="gap_fill",
            layout_primary=False,
            allow_invoice_model=True,
            field_trust_min_confidence=settings.di_field_trust_min_confidence,
            line_item_trust_min_confidence=settings.di_line_item_trust_min_confidence,
        )

    def enrich(
        self,
        ocr: OcrArtifact,
        file_path: Path,
        decision: DocumentRouteDecision,
    ) -> StrategyEnrichResult:
        settings = get_settings()
        model_id = self.config.primary_model or "prebuilt-invoice"
        if not file_path.is_file() or not is_di_enabled():
            tagged = _tag_layout_only(
                ocr, decision, self.config, skip_reason="not_configured"
            )
            return StrategyEnrichResult(
                ocr=tagged,
                audit=_base_audit(
                    decision,
                    self.config,
                    attempted=False,
                    success=False,
                    failure_reason="not_configured",
                    di_model=ocr.di_model,
                ),
            )

        content_type = _content_type_for_path(file_path)
        from app.services.extraction.di_raw_persist import (
            maybe_attach_raw_di,
            parse_invoice_with_raw,
        )

        invoice_data, raw_snapshot, outcome = parse_invoice_with_raw(
            file_path, content_type=content_type
        )
        models_run = [model_id]
        if invoice_data is None:
            tagged = _tag_layout_only(
                ocr, decision, self.config, skip_reason="no_documents"
            )
            raw_di = maybe_attach_raw_di(
                raw_snapshot, model_id=model_id, outcome="failure"
            )
            if raw_di:
                tagged.payload_json = {**tagged.payload_json, "raw_di": raw_di}
            return StrategyEnrichResult(
                ocr=tagged,
                audit=_base_audit(
                    decision,
                    self.config,
                    attempted=True,
                    success=False,
                    failure_reason="no_documents",
                    di_model=model_id,
                    models_run=models_run,
                ),
                models_run=models_run,
            )

        raw_di = maybe_attach_raw_di(raw_snapshot, model_id=model_id, outcome=outcome)
        enriched = _apply_semantic_enrich(
            ocr,
            invoice_data,
            decision=decision,
            config=self.config,
            model_id=model_id,
            models_run=models_run,
            raw_di=raw_di,
        )
        from app.services.extraction.extraction_field_values import di_scalar_fields_populated

        populated = sorted(di_scalar_fields_populated(enriched.payload_json))
        return StrategyEnrichResult(
            ocr=enriched,
            audit=_base_audit(
                decision,
                self.config,
                attempted=True,
                success=True,
                di_model=model_id,
                fields_populated=populated,
                models_run=models_run,
            ),
            models_run=models_run,
        )


class ReceiptOrClaimStrategy:
    """Expense claims may use invoice model; receipts prefer receipt model or layout."""

    def __init__(self, route: ExtractionRoute) -> None:
        settings = get_settings()
        receipt_model = (settings.azure_di_receipt_model_id or "").strip() or None
        # Default primary: receipt model if configured; invoice model only decided at enrich-time
        self.route = route
        self.config = ExtractionStrategyConfig(
            name="receipt_or_claim",
            primary_model=receipt_model,
            fallback_models=(settings.azure_di_layout_model_id or "prebuilt-layout",),
            expect_line_items=True,
            totals_authoritative=False,
            layout_line_mode="primary",
            layout_primary=True,
            allow_invoice_model=False,
            field_trust_min_confidence=settings.di_field_trust_min_confidence,
            line_item_trust_min_confidence=settings.di_line_item_trust_min_confidence,
        )

    def enrich(
        self,
        ocr: OcrArtifact,
        file_path: Path,
        decision: DocumentRouteDecision,
    ) -> StrategyEnrichResult:
        # Router decides whether expense claims may use the invoice model
        if decision.allow_invoice_model and self.route == ExtractionRoute.EXPENSE_CLAIM:
            invoice_strategy = InvoiceFamilyStrategy(ExtractionRoute.EXPENSE_CLAIM)
            result = invoice_strategy.enrich(ocr, file_path, decision)
            result.audit["extraction_strategy"] = "receipt_or_claim"
            result.ocr.payload_json = {
                **result.ocr.payload_json,
                "extraction_strategy": "receipt_or_claim",
                "extraction_route": decision.route.value,
            }
            return result

        # Receipt without model / claim without invoice permission: layout-primary
        if not self.config.primary_model:
            tagged = _tag_layout_only(
                ocr, decision, self.config, skip_reason="layout_primary"
            )
            return StrategyEnrichResult(
                ocr=tagged,
                audit=_base_audit(
                    decision,
                    self.config,
                    attempted=False,
                    success=True,
                    skip_reason="layout_primary",
                    di_model=ocr.di_model,
                ),
            )

        # Optional receipt model
        if not file_path.is_file() or not is_di_enabled():
            tagged = _tag_layout_only(
                ocr, decision, self.config, skip_reason="not_configured"
            )
            return StrategyEnrichResult(
                ocr=tagged,
                audit=_base_audit(
                    decision,
                    self.config,
                    attempted=False,
                    success=False,
                    failure_reason="not_configured",
                    di_model=ocr.di_model,
                ),
            )

        model_id = self.config.primary_model
        content_type = _content_type_for_path(file_path)
        from app.services.extraction.di_raw_persist import (
            maybe_attach_raw_di,
            parse_invoice_with_raw,
        )

        invoice_data, raw_snapshot, outcome = parse_invoice_with_raw(
            file_path,
            content_type=content_type,
            model_id_override=model_id,
        )
        models_run = [model_id]
        if invoice_data is None:
            tagged = _tag_layout_only(
                ocr, decision, self.config, skip_reason="receipt_model_failed"
            )
            raw_di = maybe_attach_raw_di(
                raw_snapshot, model_id=model_id, outcome="failure"
            )
            if raw_di:
                tagged.payload_json = {**tagged.payload_json, "raw_di": raw_di}
            return StrategyEnrichResult(
                ocr=tagged,
                audit=_base_audit(
                    decision,
                    self.config,
                    attempted=True,
                    success=False,
                    failure_reason="receipt_model_failed",
                    di_model=model_id,
                    models_run=models_run,
                ),
                models_run=models_run,
            )

        raw_di = maybe_attach_raw_di(raw_snapshot, model_id=model_id, outcome=outcome)
        enriched = _apply_semantic_enrich(
            ocr,
            invoice_data,
            decision=decision,
            config=self.config,
            model_id=model_id,
            models_run=models_run,
            raw_di=raw_di,
        )
        from app.services.extraction.extraction_field_values import di_scalar_fields_populated

        populated = sorted(di_scalar_fields_populated(enriched.payload_json))
        return StrategyEnrichResult(
            ocr=enriched,
            audit=_base_audit(
                decision,
                self.config,
                attempted=True,
                success=True,
                di_model=model_id,
                fields_populated=populated,
                models_run=models_run,
            ),
            models_run=models_run,
        )


class LayoutPrimaryStrategy:
    """PO / GRN / statement / remittance — no invoice model."""

    def __init__(self, route: ExtractionRoute) -> None:
        settings = get_settings()
        self.route = route
        self.config = ExtractionStrategyConfig(
            name="layout_primary",
            primary_model=settings.azure_di_layout_model_id or "prebuilt-layout",
            fallback_models=(settings.azure_di_read_model_id or "prebuilt-read",),
            expect_line_items=route in {ExtractionRoute.PURCHASE_ORDER, ExtractionRoute.GRN},
            totals_authoritative=False,
            layout_line_mode="primary",
            layout_primary=True,
            allow_invoice_model=False,
        )

    def enrich(
        self,
        ocr: OcrArtifact,
        file_path: Path,
        decision: DocumentRouteDecision,
    ) -> StrategyEnrichResult:
        tagged = _tag_layout_only(
            ocr, decision, self.config, skip_reason="layout_primary"
        )
        return StrategyEnrichResult(
            ocr=tagged,
            audit=_base_audit(
                decision,
                self.config,
                attempted=False,
                success=True,
                skip_reason="layout_primary",
                di_model=tagged.di_model,
            ),
        )


class LayoutOnlyReviewStrategy:
    """Supporting / unknown — layout/read only; do not treat tables as invoice lines."""

    def __init__(self, route: ExtractionRoute) -> None:
        settings = get_settings()
        self.route = route
        self.config = ExtractionStrategyConfig(
            name="layout_only_review",
            primary_model=settings.azure_di_layout_model_id or "prebuilt-layout",
            fallback_models=(settings.azure_di_read_model_id or "prebuilt-read",),
            expect_line_items=False,
            totals_authoritative=False,
            layout_line_mode="ignore",
            layout_primary=True,
            allow_invoice_model=False,
            review_on_unknown=route == ExtractionRoute.UNKNOWN,
        )

    def enrich(
        self,
        ocr: OcrArtifact,
        file_path: Path,
        decision: DocumentRouteDecision,
    ) -> StrategyEnrichResult:
        skip = "unknown_route" if decision.route == ExtractionRoute.UNKNOWN else "layout_only"
        tagged = _tag_layout_only(ocr, decision, self.config, skip_reason=skip)
        return StrategyEnrichResult(
            ocr=tagged,
            audit=_base_audit(
                decision,
                self.config,
                attempted=False,
                success=True,
                skip_reason=skip,
                di_model=tagged.di_model,
            ),
        )
