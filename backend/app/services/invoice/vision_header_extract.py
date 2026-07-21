"""Vision header extract — printed title, counterparty, linking refs for bundling/UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.models.invoice import Invoice
from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.services.extraction.vision_pdf import (
    HEADER_VISION_MAX_PAGES,
    resolve_header_vision_images,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

logger = get_logger(__name__)

CANONICAL_DOCUMENT_TYPE_KEY = "canonical_document_type"


# Below this confidence (or after heavy grounding clears), hold for header review.
VISION_HEADER_REVIEW_CONFIDENCE = 0.55


@dataclass(frozen=True)
class VisionHeaderExtractResult:
    success: bool
    document_heading: str = ""
    canonical_document_type: str = ""
    counterparty_name: str = ""
    perspective: str = "unknown"
    invoice_no: str = ""
    proforma_invoice_no: str = ""
    po_reference: str = ""
    so_reference: str = ""
    other_reference: str = ""
    invoice_date: date | None = None
    total: Decimal | None = None
    currency: str = ""
    confidence: float = 0.0
    reason: str = ""
    provider: str = ""
    page_count: int = 0
    fail_reason: str | None = None
    needs_review: bool = False


def vision_header_has_commercial_identity(result: VisionHeaderExtractResult) -> bool:
    """True when at least one linking / identity field survived extraction."""
    return bool(
        (result.document_heading or "").strip()
        or (result.canonical_document_type or "").strip()
        or (result.counterparty_name or "").strip()
        or (result.invoice_no or "").strip()
        or (result.proforma_invoice_no or "").strip()
        or (result.po_reference or "").strip()
        or (result.so_reference or "").strip()
        or (result.other_reference or "").strip()
        or result.invoice_date is not None
        or result.total is not None
    )


def vision_header_should_review(
    result: VisionHeaderExtractResult,
    *,
    grounding_cleared: list[str] | None = None,
) -> bool:
    """Hold in vision_header_review when extract is weak or heavily ungrounded."""
    if not result.success:
        return True
    if result.needs_review:
        return True
    if result.confidence < VISION_HEADER_REVIEW_CONFIDENCE:
        return True
    if grounding_cleared and len(grounding_cleared) >= 2:
        return True
    return not vision_header_has_commercial_identity(result)


def vision_header_extract_audit_detail(result: VisionHeaderExtractResult) -> dict:
    return {
        "success": result.success,
        "document_heading": result.document_heading,
        "canonical_document_type": result.canonical_document_type,
        "counterparty_name": result.counterparty_name,
        "perspective": result.perspective,
        "invoice_no": result.invoice_no,
        "proforma_invoice_no": result.proforma_invoice_no,
        "po_reference": result.po_reference,
        "so_reference": result.so_reference,
        "other_reference": result.other_reference,
        "invoice_date": result.invoice_date.isoformat() if result.invoice_date else None,
        "total": str(result.total) if result.total is not None else None,
        "currency": result.currency or None,
        "confidence": result.confidence,
        "reason": result.reason,
        "provider": result.provider,
        "page_count": result.page_count,
        "fail_reason": result.fail_reason,
        "needs_review": result.needs_review,
    }


def _raw_field(raw: dict, key: str):
    """Return the first non-empty raw value for a canonical key (incl. aliases)."""
    from app.services.invoice.vision_header_schema import VISION_HEADER_KEY_ALIASES

    aliases = VISION_HEADER_KEY_ALIASES.get(key, (key,))
    for alias in aliases:
        if alias not in raw:
            continue
        val = raw.get(alias)
        if val is None or val == "":
            continue
        return val
    if key in raw and raw.get(key) not in (None, ""):
        return raw.get(key)
    return None


def _str_field(raw: dict, key: str) -> str:
    val = _raw_field(raw, key)
    if isinstance(val, dict):
        for nested in ("value", "text", "content", "name"):
            if nested in val and val.get(nested) is not None:
                val = val.get(nested)
                break
    return str(val or "").strip()


def _normalize_perspective(value: str) -> str:
    token = (value or "").strip().lower()
    if token in {"purchase", "sales", "unknown"}:
        return token
    if token in {"buyer", "ap"}:
        return "purchase"
    if token in {"seller", "ar"}:
        return "sales"
    return "unknown"


def _parse_header_date(raw: dict) -> date | None:
    from app.services.extraction.field_validators import normalize_date

    return normalize_date(_raw_field(raw, "invoice_date"))


def _parse_header_total(raw: dict) -> Decimal | None:
    from app.services.extraction.field_validators import normalize_amount

    return normalize_amount(_raw_field(raw, "total"))


def _parse_header_currency(raw: dict) -> str:
    from app.services.extraction.field_validators import normalize_currency

    # Prefer explicit currency field; else try to recover from total token (e.g. "AUD 120.00").
    code = normalize_currency(_raw_field(raw, "currency"))
    if not code:
        total_raw = _raw_field(raw, "total")
        if total_raw is not None:
            code = normalize_currency(str(total_raw))
    return (code or "")[:3]


def parse_vision_header_raw(
    raw: dict | None,
    *,
    provider: str,
    page_count: int = 0,
) -> VisionHeaderExtractResult:
    if not isinstance(raw, dict):
        return VisionHeaderExtractResult(
            success=False,
            provider=provider,
            page_count=page_count,
            fail_reason="provider_empty_response",
        )
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return VisionHeaderExtractResult(
        success=True,
        document_heading=_str_field(raw, "document_heading")[:500],
        canonical_document_type=_str_field(raw, CANONICAL_DOCUMENT_TYPE_KEY)[:200],
        counterparty_name=_str_field(raw, "counterparty_name")[:500],
        perspective=_normalize_perspective(_str_field(raw, "perspective")),
        invoice_no=_str_field(raw, "invoice_no")[:128],
        proforma_invoice_no=_str_field(raw, "proforma_invoice_no")[:128],
        po_reference=_str_field(raw, "po_reference")[:128],
        so_reference=_str_field(raw, "so_reference")[:128],
        other_reference=_str_field(raw, "other_reference")[:128],
        invoice_date=_parse_header_date(raw),
        total=_parse_header_total(raw),
        currency=_parse_header_currency(raw),
        confidence=confidence,
        reason=_str_field(raw, "reason")[:500],
        provider=provider,
        page_count=page_count,
    )


def persist_vision_header_to_invoice(
    invoice: Invoice,
    result: VisionHeaderExtractResult,
) -> None:
    """Write header fields onto invoice columns used by Upload + dossier bundling."""
    from app.services.extraction.extraction_field_values import (
        apply_parsed_extraction_fields,
        merge_invoice_extracted_fields,
    )
    from app.services.extraction.invoice_no_sanitizer import (
        apply_invoice_no_secondary,
        sanitize_invoice_no_parts,
    )
    from app.services.shared.amount_sanity import plausible_money

    primary, secondary = sanitize_invoice_no_parts(result.invoice_no or None)
    if primary:
        invoice.invoice_no = primary
    if result.po_reference:
        invoice.po_reference = result.po_reference
    if result.so_reference:
        invoice.so_reference = result.so_reference
    from app.services.sales.so_reference import sanitize_cross_book_linkage_references

    sanitize_cross_book_linkage_references(invoice)
    if result.counterparty_name:
        invoice.vendor = result.counterparty_name
    if result.invoice_date is not None:
        invoice.invoice_date = result.invoice_date
    money = plausible_money(result.total)
    if money is not None:
        invoice.total = money
    # Always write currency from vision — empty clears any ingest/tenant seed so
    # undetected currency shows blank (UI asks user) instead of inventing AUD.
    invoice.currency = (result.currency or "").strip().upper()[:3]

    parsed = InvoiceData(
        vendor=result.counterparty_name or invoice.vendor,
        invoice_no=primary or invoice.invoice_no,
        po_reference=invoice.po_reference,
        document_heading=result.document_heading or None,
        invoice_date=result.invoice_date or invoice.invoice_date,
        total=money if money is not None else invoice.total,
        currency=invoice.currency or "",
    )
    apply_parsed_extraction_fields(invoice, parsed)

    patch: dict[str, str] = {
        "perspective": result.perspective,
        "llm_perspective": result.perspective,
    }
    if result.document_heading:
        patch["document_heading"] = result.document_heading
    if result.canonical_document_type:
        patch[CANONICAL_DOCUMENT_TYPE_KEY] = result.canonical_document_type
    if result.proforma_invoice_no:
        patch["proforma_invoice_no"] = result.proforma_invoice_no
    if result.other_reference:
        patch["other_reference"] = result.other_reference
    if invoice.so_reference:
        patch["so_reference"] = invoice.so_reference
    elif result.so_reference:
        # Cleared by cross-book sanitize — drop stale extracted copy.
        fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
        if "so_reference" in fields:
            fields = dict(fields)
            fields.pop("so_reference", None)
            invoice.extracted_fields = fields
    if result.invoice_date is not None:
        patch["invoice_date"] = result.invoice_date.isoformat()
    if money is not None:
        patch["total"] = format(money, "f")
    if invoice.currency:
        patch["currency"] = invoice.currency
    if result.counterparty_name:
        if result.perspective == "sales":
            patch["buyer_name"] = result.counterparty_name
        else:
            patch["seller_name"] = result.counterparty_name
            patch.setdefault("vendor", result.counterparty_name)
    if result.confidence > 0:
        patch["vision_header_confidence"] = f"{result.confidence:.4f}"

    merge_invoice_extracted_fields(invoice, patch)
    # Drop stale currency key when vision left currency empty.
    if not invoice.currency:
        fields = dict(invoice.extracted_fields or {})
        if fields.pop("currency", None) is not None:
            invoice.extracted_fields = fields
    if secondary:
        invoice.extracted_fields = apply_invoice_no_secondary(
            dict(invoice.extracted_fields or {}),
            secondary,
        )


async def evaluate_vision_header_extract(
    file_path: str | Path,
    *,
    provider: DocumentAiProvider,
    org: OrgContext,
    vision_page_images: list[bytes] | None = None,
) -> VisionHeaderExtractResult:
    """Rasterize + call vision header extract; never raises."""
    from app.services.extraction.document_ai_provider import (
        extract_vision_header,
        provider_available,
        provider_unavailable_reason,
    )

    provider_token = provider.value
    if provider not in (
        DocumentAiProvider.GEMINI_VISION,
        DocumentAiProvider.AZURE_FOUNDRY_VISION,
        DocumentAiProvider.CLAUDE_VISION,
    ):
        return VisionHeaderExtractResult(
            success=False,
            provider=provider_token,
            fail_reason="vision_provider_not_configured",
        )
    if not provider_available(provider):
        return VisionHeaderExtractResult(
            success=False,
            provider=provider_token,
            fail_reason=provider_unavailable_reason(provider) or "vision_unavailable",
        )

    path = Path(file_path)
    try:
        # Whole upload (up to HEADER_VISION_MAX_PAGES). Extends understand-gate
        # cache when it only held the first few pages.
        images = resolve_header_vision_images(
            path,
            vision_page_images,
            max_pages=HEADER_VISION_MAX_PAGES,
        )
    except Exception as exc:
        logger.warning("vision_header_raster_failed", error=str(exc))
        return VisionHeaderExtractResult(
            success=False,
            provider=provider_token,
            fail_reason="rasterize_failed",
        )
    if not images:
        return VisionHeaderExtractResult(
            success=False,
            provider=provider_token,
            fail_reason="no_pages",
        )

    try:
        raw = await extract_vision_header(
            provider=provider,
            images=images,
            org=org,
        )
    except Exception as exc:
        logger.warning("vision_header_extract_failed", error=str(exc))
        return VisionHeaderExtractResult(
            success=False,
            provider=provider_token,
            page_count=len(images),
            fail_reason="provider_error",
        )

    return parse_vision_header_raw(
        raw,
        provider=provider_token,
        page_count=len(images),
    )
