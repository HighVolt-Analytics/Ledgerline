"""Azure DI-first OCR extraction for the LLM classification pipeline."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.schemas.ocr_artifact import OcrArtifact
from app.services.document_intelligence import is_di_enabled, parse_with_document_intelligence
from app.services.document_layout_service import analyze_layout_via_di
from app.services.layout_field_extractor import layout_hint_suggests_invoice
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
        payload["invoice_fields"] = {
            "vendor": invoice_data.vendor,
            "invoice_no": invoice_data.invoice_no,
            "total": str(invoice_data.total) if invoice_data.total is not None else None,
        }

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


def enrich_ocr_with_invoice_model(ocr: OcrArtifact, file_path: str | Path) -> OcrArtifact:
    """Run prebuilt-invoice DI after document type is confirmed (extract phase)."""
    settings = get_settings()
    path = Path(file_path)
    if not path.is_file() or not is_di_enabled():
        return ocr

    content_type = _content_type_for_path(path)
    invoice_data = parse_with_document_intelligence(path, content_type=content_type)
    if invoice_data is None:
        return ocr

    text = ocr.text or ""
    if not text.strip() and invoice_data.document_text:
        text = invoice_data.document_text.strip()

    layout_kv = dict(ocr.layout_kv)
    payload = dict(ocr.payload_json)
    payload["invoice_fields"] = {
        "vendor": invoice_data.vendor,
        "invoice_no": invoice_data.invoice_no,
        "total": str(invoice_data.total) if invoice_data.total is not None else None,
    }
    payload["di_model"] = settings.azure_di_model_id or "prebuilt-invoice"
    payload["provider"] = "azure_di"

    text_length = len(text)
    sparse = text_length < settings.ocr_min_text_chars
    return OcrArtifact(
        success=True,
        sparse=sparse,
        text=text,
        text_length=text_length,
        di_model=str(payload["di_model"]),
        layout_kv=layout_kv,
        payload_json=payload,
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
    if layout is None or layout_hint_suggests_invoice("invoice"):
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
