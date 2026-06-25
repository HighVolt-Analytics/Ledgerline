"""Apply gate for document-type sample analysis."""

from app.schemas.document_type_sample_analysis import (
    DocumentTypeSampleFileResult,
    DocumentTypeSampleProposal,
)
from app.services.document_type_recognition_signals import NO_SHARED_IDENTITY_NOTE
from app.services.document_type_sample_analyzer import compute_apply_ready


def _proposal(**kwargs) -> DocumentTypeSampleProposal:
    base = dict(
        recognition_signals=["heading_invoice", "has_invoice_number"],
        samples=[
            DocumentTypeSampleFileResult(
                filename="a.pdf",
                recognition_signals=["heading_invoice", "has_invoice_number"],
            )
        ],
        notes=[],
        apply_ready=False,
    )
    base.update(kwargs)
    return DocumentTypeSampleProposal(**base)


def test_apply_ready_without_catalogue_preview() -> None:
    ready, reason = compute_apply_ready(_proposal(), has_catalogue_preview=False)
    assert ready is True
    assert reason is None


def test_apply_ready_blocked_without_signals() -> None:
    ready, reason = compute_apply_ready(
        _proposal(recognition_signals=[], notes=["No recognition signals detected"]),
        has_catalogue_preview=False,
    )
    assert ready is False
    assert reason


def test_apply_ready_blocked_on_shared_identity_note() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            recognition_signals=[],
            notes=[NO_SHARED_IDENTITY_NOTE],
        ),
        has_catalogue_preview=False,
    )
    assert ready is False
    assert "same document type" in (reason or "")


def test_apply_ready_blocked_on_catalogue_mismatch() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            samples=[
                DocumentTypeSampleFileResult(
                    filename="a.pdf",
                    recognition_signals=["heading_invoice"],
                    routed_code="DT-02",
                    routed_confidence=0.9,
                    matches_expected=False,
                )
            ]
        ),
        has_catalogue_preview=True,
    )
    assert ready is False
    assert "does not match" in (reason or "").lower()


def test_apply_ready_allows_conflicts_when_proposed_matches() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            samples=[
                DocumentTypeSampleFileResult(
                    filename="a.pdf",
                    recognition_signals=["heading_contract"],
                    routed_code="DT-99",
                    routed_confidence=0.9,
                    matches_expected=True,
                    route_conflicts=["has_invoice_no vs supporting_doc guard"],
                )
            ]
        ),
        has_catalogue_preview=True,
    )
    assert ready is True
    assert reason is None


def test_apply_ready_blocked_on_route_conflicts_without_proposed_match() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            samples=[
                DocumentTypeSampleFileResult(
                    filename="a.pdf",
                    recognition_signals=["heading_invoice"],
                    routed_code="DT-01",
                    routed_confidence=0.9,
                    matches_expected=None,
                    route_conflicts=["has_po_reference vs absent invoice_no"],
                )
            ]
        ),
        has_catalogue_preview=True,
    )
    assert ready is False
    assert "conflicts" in (reason or "").lower()


def test_apply_ready_allows_ambiguous_alternatives_when_proposed_matches() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            samples=[
                DocumentTypeSampleFileResult(
                    filename="a.pdf",
                    recognition_signals=["heading_contract"],
                    routed_code="DT-99",
                    routed_confidence=0.72,
                    matches_expected=True,
                    route_alternatives=[
                        {"code": "DT-06", "confidence": 0.7, "reason": "alt"},
                    ],
                )
            ]
        ),
        has_catalogue_preview=True,
    )
    assert ready is True
    assert reason is None


def test_apply_ready_blocked_on_ambiguous_alternatives() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            samples=[
                DocumentTypeSampleFileResult(
                    filename="a.pdf",
                    recognition_signals=["heading_invoice"],
                    routed_code="DT-01",
                    routed_confidence=0.72,
                    matches_expected=None,
                    route_alternatives=[
                        {"code": "DT-02", "confidence": 0.7, "reason": "alt"},
                    ],
                )
            ]
        ),
        has_catalogue_preview=True,
    )
    assert ready is False
    assert "ambiguous" in (reason or "").lower()


def test_apply_ready_passes_clean_catalogue_preview() -> None:
    ready, reason = compute_apply_ready(
        _proposal(
            samples=[
                DocumentTypeSampleFileResult(
                    filename="a.pdf",
                    recognition_signals=["heading_invoice"],
                    routed_code="DT-01",
                    routed_confidence=0.92,
                    matches_expected=True,
                    route_alternatives=[
                        {"code": "DT-02", "confidence": 0.4, "reason": "weak alt"},
                    ],
                )
            ]
        ),
        has_catalogue_preview=True,
    )
    assert ready is True
    assert reason is None
