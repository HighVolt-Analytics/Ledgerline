"""Field-level candidate collection and resolution."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Sequence

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_field_values import (
    EXTRACTED_ONLY_ATTRS,
    INVOICE_SCALAR_ATTRS,
    extracted_fields_from_parsed,
    merge_extracted_field_maps,
)
from app.services.extraction.field_contracts import (
    ExtractionFieldContract,
    FieldCandidate,
    FieldResolutionResult,
    FieldSource,
    ResolutionStatus,
    normalize_field_source,
)
from app.services.extraction.field_validators import (
    normalize_abn,
    normalize_field_value,
    normalize_invoice_no,
    validate_normalized,
)
from app.services.extraction.layout_field_extractor import (
    extract_key_value_fields,
    normalize_layout_kv_dict,
)
from app.services.extraction.pdf_parser import parse_local_text
from app.services.invoice.invoice_data import InvoiceData
from app.services.master_data.vendor_name_utils import normalize_vendor_name


def _scalar_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def _value_grounded(key: str, value: object, ocr_text: str | None) -> bool:
    if not ocr_text or value is None:
        return False
    from app.services.extraction.field_grounding_service import value_grounded_in_ocr

    try:
        return bool(value_grounded_in_ocr(value, ocr_text, field_key=key))
    except Exception:  # noqa: BLE001
        token = str(value).strip()
        return bool(token) and token.lower() in ocr_text.lower()


def _di_confidence_map(payload: dict[str, object]) -> dict[str, float]:
    raw = payload.get("field_confidence")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key).strip().lower()] = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return out


def collect_di_candidates(
    payload: dict[str, object],
    *,
    ocr_text: str | None,
    keys: Sequence[str],
) -> dict[str, list[FieldCandidate]]:
    fields = payload.get("invoice_fields")
    if not isinstance(fields, dict):
        return {}
    conf_map = _di_confidence_map(payload)
    party = payload.get("di_party_fields") if isinstance(payload.get("di_party_fields"), dict) else {}
    out: dict[str, list[FieldCandidate]] = {}
    for key in keys:
        raw = fields.get(key)
        if _scalar_empty(raw) and isinstance(party, dict):
            # party aliases
            if key == "abn":
                raw = party.get("seller_abn") or party.get("seller_tax_id") or fields.get("abn")
            elif key == "vendor":
                raw = fields.get("vendor") or party.get("seller_name")
        if _scalar_empty(raw):
            continue
        grounded = _value_grounded(key, raw, ocr_text)
        out.setdefault(key, []).append(
            FieldCandidate(
                source=FieldSource.SEMANTIC_DI.value,
                value=raw,
                confidence=conf_map.get(key),
                grounded=grounded,
                raw_metadata={"di_field": key},
            )
        )
    return out


def collect_layout_kv_candidates(
    ocr: OcrArtifact,
    *,
    ocr_text: str | None,
    keys: Sequence[str],
) -> dict[str, list[FieldCandidate]]:
    kv = normalize_layout_kv_dict(dict(ocr.layout_kv or {}))
    payload = dict(ocr.payload_json or {})
    payload_kv = payload.get("layout_kv") if isinstance(payload.get("layout_kv"), dict) else {}
    if payload_kv:
        for key, value in normalize_layout_kv_dict(
            {str(k): str(v) for k, v in payload_kv.items() if v is not None}  # type: ignore[arg-type]
        ).items():
            kv.setdefault(key, value)
    if ocr_text:
        for key, value in extract_key_value_fields(None, ocr_text).items():
            kv.setdefault(key, value)
    out: dict[str, list[FieldCandidate]] = {}
    for key in keys:
        raw = kv.get(key)
        if _scalar_empty(raw):
            continue
        out.setdefault(key, []).append(
            FieldCandidate(
                source=FieldSource.LAYOUT_KV.value,
                value=raw,
                confidence=None,
                grounded=_value_grounded(key, raw, ocr_text),
            )
        )
    return out


def collect_regex_candidates(
    ocr_text: str | None,
    *,
    keys: Sequence[str],
) -> dict[str, list[FieldCandidate]]:
    if not ocr_text:
        return {}
    local = parse_local_text(ocr_text)
    out: dict[str, list[FieldCandidate]] = {}
    for key in keys:
        if key == "line_items":
            continue
        if hasattr(local, key):
            raw = getattr(local, key)
        else:
            raw = (local.extracted_fields or {}).get(key) if local.extracted_fields else None
            if raw is None and local.raw_fields:
                raw = local.raw_fields.get(key)
        if _scalar_empty(raw):
            continue
        out.setdefault(key, []).append(
            FieldCandidate(
                source=FieldSource.REGEX.value,
                value=raw,
                confidence=None,
                grounded=_value_grounded(key, raw, ocr_text),
            )
        )
    return out


def collect_llm_candidates(
    parsed: InvoiceData,
    *,
    ocr_text: str | None,
    keys: Sequence[str],
) -> dict[str, list[FieldCandidate]]:
    out: dict[str, list[FieldCandidate]] = {}
    extracted = extracted_fields_from_parsed(parsed)
    for key in keys:
        if key == "line_items":
            raw = parsed.line_items
        elif key in INVOICE_SCALAR_ATTRS:
            raw = getattr(parsed, key, None)
        else:
            raw = extracted.get(key)
        if _scalar_empty(raw):
            continue
        out.setdefault(key, []).append(
            FieldCandidate(
                source=FieldSource.LLM.value,
                value=raw,
                confidence=None,
                grounded=_value_grounded(key, raw, ocr_text) if key != "line_items" else True,
            )
        )
    return out


def collect_line_item_candidates(
    payload: dict[str, object],
) -> list[FieldCandidate]:
    from app.services.extraction.line_items_parser import resolve_line_items_for_strategy

    layout_mode = str(payload.get("layout_line_mode") or "gap_fill").strip().lower()
    rows = resolve_line_items_for_strategy(payload, layout_mode=layout_mode, allow_qty_only=True)
    if not rows:
        return []
    source = FieldSource.LAYOUT_TABLE.value
    if payload.get("di_line_items") and layout_mode in {"gap_fill", "gap_fill_append", "ignore"}:
        source = FieldSource.SEMANTIC_DI.value
    return [
        FieldCandidate(
            source=source,
            value=rows,
            confidence=None,
            grounded=True,
            raw_metadata={"layout_line_mode": layout_mode, "count": len(rows)},
        )
    ]


def _min_confidence(contract: ExtractionFieldContract) -> float:
    if contract.min_confidence is not None:
        return float(contract.min_confidence)
    return float(get_settings().di_field_trust_min_confidence)


def _normalize_for_key(contract: ExtractionFieldContract, value: Any) -> Any:
    key = contract.key
    if key == "abn" or key.endswith("_abn"):
        return normalize_abn(value)
    if key == "invoice_no":
        return normalize_invoice_no(value)
    if key == "vendor":
        token = normalize_vendor_name(str(value)) if value is not None else None
        return token or (str(value).strip() if value else None)
    if key == "currency":
        from app.services.extraction.field_validators import normalize_currency

        return normalize_currency(value) or ""
    return normalize_field_value(contract.field_type, value)


def resolve_field_value(
    contract: ExtractionFieldContract,
    candidates: Sequence[FieldCandidate],
    *,
    context: dict[str, Any] | None = None,
) -> FieldResolutionResult:
    """Select a single accepted value for one field contract."""
    _ = context
    rejected: list[dict[str, Any]] = []
    eligible: list[FieldCandidate] = []
    min_conf = _min_confidence(contract)

    for candidate in candidates:
        if not contract.allows_source(candidate.source):
            rejected.append(
                {
                    "source": candidate.source,
                    "reason": "source_not_allowed",
                    "value": str(candidate.value)[:120] if candidate.value is not None else None,
                }
            )
            continue
        source = normalize_field_source(candidate.source)
        conf = candidate.confidence
        if source == FieldSource.SEMANTIC_DI and conf is not None and conf < min_conf:
            rejected.append(
                {
                    "source": candidate.source,
                    "reason": "low_confidence",
                    "confidence": conf,
                }
            )
            continue
        if contract.grounding_required and not candidate.grounded:
            # Allow DI/LLM through with warning path only when confidence is high
            if source == FieldSource.SEMANTIC_DI and conf is not None and conf >= min_conf:
                pass
            elif source == FieldSource.LLM and conf is None:
                # LLM still eligible; grounding checked softly
                pass
            else:
                rejected.append(
                    {
                        "source": candidate.source,
                        "reason": "not_grounded",
                    }
                )
                continue
        eligible.append(candidate)

    if not eligible:
        status = (
            ResolutionStatus.REVIEW_REQUIRED
            if contract.required or contract.review_if_missing
            else ResolutionStatus.MISSING
        )
        return FieldResolutionResult(
            key=contract.key,
            resolution_status=status,
            review_reason="missing" if status != ResolutionStatus.MISSING else None,
            rejected_candidates=rejected,
            target_column=contract.target_column or contract.key,
        )

    eligible_sorted = sorted(
        eligible,
        key=lambda c: (
            contract.source_rank(c.source),
            -(c.confidence if c.confidence is not None else -1.0),
            0 if c.grounded else 1,
        ),
    )
    winner = eligible_sorted[0]
    normalized = _normalize_for_key(contract, winner.value)
    ok, reason = validate_normalized(contract.field_type, normalized, key=contract.key)
    if not ok:
        rejected.append(
            {
                "source": winner.source,
                "reason": reason or "validation_failed",
            }
        )
        status = (
            ResolutionStatus.REVIEW_REQUIRED
            if contract.required
            else ResolutionStatus.REJECTED
        )
        return FieldResolutionResult(
            key=contract.key,
            resolution_status=status,
            review_reason=reason,
            rejected_candidates=rejected,
            target_column=contract.target_column or contract.key,
        )

    warning = None
    status = ResolutionStatus.ACCEPTED
    if contract.grounding_required and not winner.grounded:
        status = ResolutionStatus.ACCEPTED_WITH_WARNING
        warning = "accepted_ungrounded"
    if (
        winner.confidence is not None
        and winner.confidence < min_conf
        and contract.review_if_low_confidence
    ):
        status = ResolutionStatus.ACCEPTED_WITH_WARNING
        warning = warning or "low_confidence"

    return FieldResolutionResult(
        key=contract.key,
        value=normalized,
        chosen_source=winner.source,
        confidence=winner.confidence,
        resolution_status=status,
        review_reason=warning,
        rejected_candidates=rejected,
        grounded=bool(winner.grounded),
        target_column=contract.target_column or contract.key,
    )


def resolve_all_fields(
    contracts: Sequence[ExtractionFieldContract],
    *,
    parsed: InvoiceData,
    ocr: OcrArtifact,
) -> list[FieldResolutionResult]:
    keys = [c.key for c in contracts]
    text = (ocr.text or parsed.document_text or "").strip() or None
    payload = dict(ocr.payload_json or {})

    by_key: dict[str, list[FieldCandidate]] = {k: [] for k in keys}
    for collector in (
        collect_di_candidates(payload, ocr_text=text, keys=keys),
        collect_layout_kv_candidates(ocr, ocr_text=text, keys=keys),
        collect_regex_candidates(text, keys=keys),
        collect_llm_candidates(parsed, ocr_text=text, keys=keys),
    ):
        for key, rows in collector.items():
            by_key.setdefault(key, []).extend(rows)

    if "line_items" in by_key:
        by_key["line_items"] = collect_line_item_candidates(payload) + by_key.get("line_items", [])

    results: list[FieldResolutionResult] = []
    for contract in contracts:
        results.append(resolve_field_value(contract, by_key.get(contract.key, [])))
    return results


def project_resolution_to_invoice_data(
    parsed: InvoiceData,
    results: Sequence[FieldResolutionResult],
    *,
    contracts: Sequence[ExtractionFieldContract] | None = None,
) -> InvoiceData:
    """Project accepted field resolutions onto InvoiceData + extracted_fields."""
    contract_by_key = {c.key: c for c in (contracts or [])}
    updates: dict[str, Any] = {}
    extracted = dict(extracted_fields_from_parsed(parsed))

    for result in results:
        if result.resolution_status not in {
            ResolutionStatus.ACCEPTED,
            ResolutionStatus.ACCEPTED_WITH_WARNING,
        }:
            continue
        key = result.key
        value = result.value
        contract = contract_by_key.get(key)
        target = (result.target_column or (contract.target_column if contract else key) or key).strip()

        if key == "line_items" and isinstance(value, list):
            updates["line_items"] = value
            continue
        if target in INVOICE_SCALAR_ATTRS or key in INVOICE_SCALAR_ATTRS:
            attr = target if target in INVOICE_SCALAR_ATTRS else key
            if attr == "currency":
                updates[attr] = value if value is not None else ""
            else:
                updates[attr] = value
            # Keep seller_abn evidence when abn projected
            if key == "abn" and value:
                extracted.setdefault("seller_abn", str(value))
            continue
        if target in EXTRACTED_ONLY_ATTRS or key in EXTRACTED_ONLY_ATTRS or (
            contract and not contract.canonical
        ):
            if value is not None and str(value).strip():
                extracted[target or key] = str(value).strip() if not isinstance(value, (list, dict)) else value
            continue
        # Custom → extracted_fields
        if value is not None and str(value).strip():
            extracted[key] = str(value).strip() if not isinstance(value, (list, dict)) else value

    if extracted != extracted_fields_from_parsed(parsed):
        updates["extracted_fields"] = merge_extracted_field_maps(extracted)
    if not updates:
        return parsed
    return replace(parsed, **updates)


def attach_field_resolution_audit(
    ocr: OcrArtifact,
    results: Sequence[FieldResolutionResult],
    *,
    contracts: Sequence[ExtractionFieldContract] | None = None,
) -> OcrArtifact:
    payload = dict(ocr.payload_json or {})
    payload["field_resolution"] = {
        r.key: r.to_audit_dict() for r in results
    }
    if contracts is not None:
        payload["resolved_contracts"] = [
            {
                "key": c.key,
                "required": c.required,
                "canonical": c.canonical,
                "allowed_sources": list(c.allowed_sources),
                "authoritative_source_order": list(c.authoritative_source_order),
            }
            for c in contracts
        ]
        payload["selected_keys"] = [c.key for c in contracts]
    return ocr.model_copy(update={"payload_json": payload})


def merge_via_field_contracts(
    parsed: InvoiceData,
    ocr: OcrArtifact,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
    contracts: Sequence[ExtractionFieldContract] | None = None,
    trace: object | None = None,
) -> tuple[InvoiceData, OcrArtifact, list[FieldResolutionResult]]:
    """Contract-driven merge: resolve fields → project → attach audit."""
    from app.services.extraction.field_contract_resolver import (
        resolve_extraction_field_contracts_for_dt,
        resolve_extraction_route_for_dt,
    )
    from app.services.extraction.pdf_parser import post_process_parsed_data

    route = None
    payload = dict(ocr.payload_json or {})
    if payload.get("extraction_route"):
        route = str(payload.get("extraction_route"))
    if contracts is None:
        if dt_definition is None:
            contracts = []
        else:
            contracts = resolve_extraction_field_contracts_for_dt(
                [dt_definition],
                dt_definition.code or "",
                route=route or resolve_extraction_route_for_dt(dt_definition),
                dt_definition=dt_definition,
            )

    # Refresh table rows from grids before collecting line-item candidates
    if payload.get("layout_table_grids"):
        from app.services.extraction.line_items_parser import (
            parse_line_items_from_layout_grids,
            serialize_line_items,
        )
        from app.services.extraction.line_items_sanitizer import sanitize_line_items

        refreshed = sanitize_line_items(
            parse_line_items_from_layout_grids(payload),
            allow_qty_only=True,
            trace=trace,
        )
        if refreshed:
            payload["table_line_items"] = serialize_line_items(refreshed)
            ocr = ocr.model_copy(update={"payload_json": payload})

    results = resolve_all_fields(contracts, parsed=parsed, ocr=ocr)
    merged = project_resolution_to_invoice_data(parsed, results, contracts=contracts)
    text = (ocr.text or merged.document_text or "").strip()
    if text and not (merged.document_text or "").strip():
        merged = replace(merged, document_text=text)

    def _sanitize_rows(rows: list) -> list:
        from app.services.extraction.line_items_parser import document_has_qty_only_table
        from app.services.extraction.line_items_sanitizer import sanitize_line_items

        return sanitize_line_items(
            list(rows),
            extracted_fields=merged.extracted_fields,
            vendor=merged.vendor,
            invoice_no=merged.invoice_no,
            po_reference=merged.po_reference,
            so_reference=(merged.extracted_fields or {}).get("so_reference"),
            cost_centre=merged.cost_centre,
            allow_qty_only=document_has_qty_only_table(text, payload),
            trace=trace,
        )

    if merged.line_items:
        merged = replace(merged, line_items=_sanitize_rows(merged.line_items))
    elif text:
        # Contracts may omit/miss line_items; reuse shape-aware DI/layout merge
        # instead of leaving the list empty for noisy text fallback.
        from app.services.extraction.extraction_orchestrator import _merge_line_items_from_sources

        seed = merged
        if not seed.line_items and parsed.line_items:
            seed = replace(merged, line_items=list(parsed.line_items))
        filled = _merge_line_items_from_sources(seed, text, payload)
        if filled:
            merged = replace(merged, line_items=_sanitize_rows(filled))
        elif seed.line_items:
            merged = replace(merged, line_items=_sanitize_rows(seed.line_items))

    merged = post_process_parsed_data(merged, text, dt_definition=dt_definition)

    from app.services.shared.currency import apply_currency_ocr_fallback

    merged = apply_currency_ocr_fallback(merged, text)  # type: ignore[assignment]

    # Apply absent fields
    if dt_definition is not None:
        absent = {
            str(f).strip().lower()
            for f in (dt_definition.absent_fields or [])
            if str(f).strip()
        }
        if absent:
            clear: dict[str, Any] = {}
            for key in absent:
                if key == "line_items":
                    clear["line_items"] = []
                elif key in INVOICE_SCALAR_ATTRS:
                    clear[key] = "" if key == "currency" else None
            extracted = dict(extracted_fields_from_parsed(merged))
            for key in absent:
                extracted.pop(key, None)
            if extracted != extracted_fields_from_parsed(merged):
                clear["extracted_fields"] = extracted
            if clear:
                merged = replace(merged, **clear)

    ocr = attach_field_resolution_audit(ocr, results, contracts=contracts)
    return merged, ocr, results
