"""Azure DI-first OCR extraction for the LLM classification pipeline."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.document_intelligence import is_di_enabled, parse_with_document_intelligence
from app.services.extraction.document_layout_service import analyze_layout_via_di
from app.services.extraction.extraction_field_values import (
    di_scalar_fields_populated,
    prebuilt_invoice_scalars_active,
)
from app.services.extraction.extraction_orchestrator import (
    invoice_data_to_payload_fields,
    should_run_prebuilt_invoice_di,
)
from app.services.extraction.layout_field_extractor import (
    extract_line_items_from_tables,
    infer_doc_family_hint,
    layout_hint_suggests_invoice,
)
from app.services.extraction.line_items_parser import serialize_line_items
from app.services.extraction.routing import (
    get_extraction_strategy,
    route_document_for_extraction,
)
from app.services.extraction.routing.decision import DocumentRouteDecision
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OcrFailed(Exception):
    """DI OCR could not produce usable text."""


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "application/pdf"


def _artifact_from_layout(
    layout,
    *,
    di_model: str,
    invoice_data=None,
) -> OcrArtifact:
    settings = get_settings()
    text = (layout.content or "").strip() if layout is not None else ""
    layout_kv: dict[str, str] = {}
    if layout is not None:
        for pair in layout.key_value_pairs:
            if pair.key and pair.value:
                layout_kv[pair.key.strip()] = pair.value.strip()

    if invoice_data is not None and not text and invoice_data.document_text:
        text = invoice_data.document_text.strip()

    text_length = len(text)
    sparse = text_length < settings.ocr_min_text_chars
    payload: dict[str, object] = {
        "text_length": text_length,
        "layout_kv": layout_kv,
        "di_model": di_model,
        "provider": "azure_di",
    }
    if invoice_data is not None:
        payload["invoice_fields"] = invoice_data_to_payload_fields(invoice_data)
        if invoice_data.line_items:
            payload["di_line_items"] = serialize_line_items(invoice_data.line_items)
        from app.services.extraction.extraction_field_values import attach_di_metadata_to_payload

        attach_di_metadata_to_payload(payload, invoice_data)

    if layout is not None:
        table_items = extract_line_items_from_tables(layout)
        if table_items:
            payload["table_line_items"] = serialize_line_items(table_items)
        from app.services.extraction.money_scalar_resolver import serialize_layout_table_grids

        grids = serialize_layout_table_grids(layout)
        if grids:
            payload["layout_table_grids"] = grids

    return OcrArtifact(
        success=True,
        sparse=sparse,
        text=text,
        text_length=text_length,
        di_model=di_model,
        layout_kv=layout_kv,
        payload_json=payload,
    )


def read_layout_for_classification(file_path: str | Path) -> OcrArtifact:
    """Layout/read OCR only — no prebuilt-invoice field model (classify gate)."""
    settings = get_settings()
    path = Path(file_path)
    if not path.is_file():
        raise OcrFailed("stored_file_missing")
    if not is_di_enabled():
        raise OcrFailed("di_not_configured")

    content_type = _content_type_for_path(path)
    layout = analyze_layout_via_di(path, content_type=content_type)
    di_model = settings.azure_di_layout_model_id or "prebuilt-layout"
    if layout is None or not (layout.content or "").strip():
        raise OcrFailed("di_analyze_failed")

    artifact = _artifact_from_layout(layout, di_model=di_model)
    logger.info(
        "di_layout_read_ok",
        path=str(path),
        text_length=artifact.text_length,
        sparse=artifact.sparse,
    )
    return artifact


def build_di_enrich_audit_detail(
    before: OcrArtifact,
    after: OcrArtifact,
    *,
    confirmed_dt: str = "",
    dt_definition=None,
    failure_reason: str | None = None,
    decision: DocumentRouteDecision | None = None,
) -> dict[str, object]:
    """Audit payload for DI enrich attempt (route-aware)."""
    settings = get_settings()
    if decision is None:
        decision = route_document_for_extraction(confirmed_dt, dt_definition)

    if not is_di_enabled():
        return {
            "attempted": False,
            "success": False,
            "failure_reason": "not_configured",
            "di_model": before.di_model,
            "fields_populated": [],
            "extraction_route": decision.route.value,
            "confirmed_dt": decision.confirmed_dt,
        }
    if not decision.uses_invoice_model:
        # Not a failure — route intentionally skipped the invoice model
        skip = failure_reason or "layout_primary"
        return {
            "attempted": False,
            "success": True,
            "failure_reason": None,
            "skip_reason": skip,
            "di_model": before.di_model,
            "fields_populated": [],
            "extraction_route": decision.route.value,
            "extraction_strategy": (after.payload_json or {}).get("extraction_strategy"),
            "confirmed_dt": decision.confirmed_dt,
            "route_reasons": list(decision.reasons),
        }

    after_payload = after.payload_json or {}
    before_payload = before.payload_json or {}
    enriched = "invoice_fields" in after_payload and "invoice_fields" not in before_payload
    if not enriched and after.di_model != before.di_model:
        enriched = prebuilt_invoice_scalars_active(after_payload)
    populated = sorted(di_scalar_fields_populated(after_payload)) if enriched else []
    success = bool(populated) or enriched
    return {
        "attempted": True,
        "success": success,
        "failure_reason": failure_reason,
        "di_model": after.di_model or settings.azure_di_model_id or "prebuilt-invoice",
        "fields_populated": populated,
        "confirmed_dt": decision.confirmed_dt or (confirmed_dt or "").strip().upper(),
        "extraction_route": decision.route.value,
        "extraction_strategy": after_payload.get("extraction_strategy"),
        "route_reasons": list(decision.reasons),
    }


def enrich_ocr_for_route(
    ocr: OcrArtifact,
    file_path: str | Path,
    *,
    confirmed_dt: str = "",
    dt_definition: DocumentTypeDefinition | None = None,
    decision: DocumentRouteDecision | None = None,
) -> tuple[OcrArtifact, dict[str, object]]:
    """Run the route-specific extraction strategy after document type is confirmed."""
    path = Path(file_path)
    if decision is None:
        decision = route_document_for_extraction(
            confirmed_dt,
            dt_definition,
            ocr=ocr,
            file_path=path if path.is_file() else None,
        )
    strategy = get_extraction_strategy(decision.route)
    result = strategy.enrich(ocr, path, decision)
    logger.info(
        "di_route_enrich",
        route=decision.route.value,
        strategy=strategy.config.name,
        success=result.audit.get("success"),
        failure_reason=result.audit.get("failure_reason"),
        skip_reason=result.audit.get("skip_reason"),
        models_run=result.models_run,
    )
    return result.ocr, result.audit


def enrich_ocr_with_invoice_model(
    ocr: OcrArtifact,
    file_path: str | Path,
    *,
    confirmed_dt: str = "",
    dt_definition=None,
) -> tuple[OcrArtifact, dict[str, object]]:
    """
    Backward-compatible enrich entry point.

    Delegates to route-aware enrich_ocr_for_route. Layout line items no longer
    block prebuilt-invoice for invoice-family routes.
    """
    return enrich_ocr_for_route(
        ocr,
        file_path,
        confirmed_dt=confirmed_dt,
        dt_definition=dt_definition,
    )


def extract_from_file(file_path: str | Path) -> OcrArtifact:
    """
    DI-first: layout/read text, optional prebuilt-invoice when invoice-like.
    Legacy full read — prefer read_layout_for_classification + enrich split.
    """
    settings = get_settings()
    path = Path(file_path)
    if not path.is_file():
        raise OcrFailed("stored_file_missing")
    if not is_di_enabled():
        raise OcrFailed("di_not_configured")

    content_type = _content_type_for_path(path)
    layout = analyze_layout_via_di(path, content_type=content_type)
    di_model = settings.azure_di_layout_model_id or "prebuilt-layout"
    invoice_data = None
    layout_text = (layout.content or "").strip() if layout is not None else ""
    family_hint = infer_doc_family_hint(layout, layout_text[:500] if layout_text else "", layout_text)
    if layout is None or layout_hint_suggests_invoice(family_hint):
        invoice_data = parse_with_document_intelligence(path, content_type=content_type)
        if invoice_data is not None:
            di_model = settings.azure_di_model_id or "prebuilt-invoice"

    artifact = _artifact_from_layout(layout, di_model=di_model, invoice_data=invoice_data)
    if not artifact.text and layout is None and invoice_data is None:
        raise OcrFailed("di_analyze_failed")

    logger.info(
        "di_extract_ok",
        path=str(path),
        text_length=artifact.text_length,
        sparse=artifact.sparse,
        model=artifact.di_model,
    )
    return artifact
