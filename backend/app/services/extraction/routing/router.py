"""Route confirmed DT (+ optional classifier) to an ExtractionRoute decision."""

from __future__ import annotations

from pathlib import Path

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.routing.classifier_port import get_document_classifier
from app.services.extraction.routing.decision import DocumentRouteDecision
from app.services.extraction.routing.dt_route_map import resolve_org_extraction_route
from app.services.extraction.routing.routes import ExtractionRoute


def route_document_for_extraction(
    confirmed_dt: str,
    dt_definition: DocumentTypeDefinition | None = None,
    *,
    ocr: OcrArtifact | None = None,
    file_path: str | Path | None = None,
) -> DocumentRouteDecision:
    """
    Decide extraction route from org DT metadata (not a hardcoded DT-code matrix).

    Order: optional classifier port → bundle roles → playbook → azure_di_profile
    → title hints → unknown.
    """
    dt_token = (confirmed_dt or "").strip().upper()
    playbook = ""
    if dt_definition is not None:
        from app.services.classification.document_type_catalog import playbook_profile_for_dt

        playbook = playbook_profile_for_dt(dt_definition)

    if file_path is not None:
        classifier = get_document_classifier()
        classified = classifier.classify(
            Path(file_path),
            confirmed_dt=dt_token,
            dt_definition=dt_definition,
            ocr=ocr,
        )
        if classified is not None:
            return classified

    if dt_definition is None and not dt_token:
        return DocumentRouteDecision(
            route=ExtractionRoute.UNKNOWN,
            confirmed_dt="",
            playbook="",
            reasons=("missing_dt_definition",),
            classifier_source="org_metadata",
            allow_invoice_model=False,
            review_hints=("EXTRACTION_GAP",),
        )

    # When only a code is provided, still resolve playbook/azure via catalog helpers
    # through a minimal definition if needed — callers should pass org definition.
    route, reasons, allow_invoice = resolve_org_extraction_route(
        confirmed_dt=dt_token,
        dt_definition=dt_definition,
        playbook=playbook,
    )

    review_hints: tuple[str, ...] = ()
    if route == ExtractionRoute.UNKNOWN:
        if not dt_token:
            review_hints = ("EXTRACTION_GAP",)
        elif dt_definition is None:
            review_hints = ("DT_NOT_IN_CATALOGUE",)
        else:
            review_hints = ("EXTRACTION_GAP",)

    if allow_invoice and route == ExtractionRoute.EXPENSE_CLAIM:
        reasons = list(reasons) + ["expense_claim_allow_invoice_model"]

    return DocumentRouteDecision(
        route=route,
        confirmed_dt=dt_token,
        playbook=playbook,
        reasons=tuple(reasons),
        classifier_source="org_metadata",
        allow_invoice_model=allow_invoice and route == ExtractionRoute.EXPENSE_CLAIM,
        review_hints=review_hints,
    )
