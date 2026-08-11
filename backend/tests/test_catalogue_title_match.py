"""Catalogue-driven vision title → DT matching (no hardcoded document names)."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.catalogue_title_match import (
    match_catalogue_dt_by_vision_title,
    score_definition_for_vision_title,
)


def _dt(
    code: str,
    *,
    title: str,
    short_title: str | None = None,
    prompt: str = "",
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=title,
        shortTitle=short_title or title,
        klass="Transactional",
        posting="Yes",
        recognitionMode="prompt",
        recognitionSignals=[],
        llmPrompt=prompt,
        routeTarget="Purchase Management",
        enabled=True,
    )


def test_exact_short_title_wins() -> None:
    advance = _dt(
        "DT-05",
        title="Advance requisition",
        short_title="Advance Requisition",
        prompt="Advance Requisition for employee cash. Do not classify Payment Voucher.",
    )
    voucher = _dt(
        "DT-06",
        title="Payment Voucher",
        short_title="Payment Voucher",
        prompt="Payment Voucher. Do not classify Advance Requisition.",
    )
    hit = match_catalogue_dt_by_vision_title(
        document_heading="Advance Requisition",
        document_types=[voucher, advance],
    )
    assert hit is not None
    best, score, runner_code, _ = hit
    assert best.code == "DT-05"
    assert score >= 0.98
    assert runner_code is None or runner_code == "DT-06"


def test_form_suffix_still_matches_short_title() -> None:
    advance = _dt(
        "DT-05",
        title="Advance requisition",
        short_title="Advance Requisition",
    )
    hit = match_catalogue_dt_by_vision_title(
        document_heading="Advance Requisition Form",
        document_types=[advance],
    )
    assert hit is not None
    assert hit[0].code == "DT-05"
    assert hit[1] >= 0.92


def test_ambiguous_similar_titles_return_none() -> None:
    a = _dt("DT-A", title="Goods Receipt Note", short_title="Goods Receipt")
    b = _dt("DT-B", title="Goods Receipt Advice", short_title="Goods Receipt")
    hit = match_catalogue_dt_by_vision_title(
        document_heading="Goods Receipt",
        document_types=[a, b],
    )
    assert hit is None


def test_unrelated_title_does_not_match() -> None:
    voucher = _dt("DT-06", title="Payment Voucher", short_title="Payment Voucher")
    assert (
        score_definition_for_vision_title("Advance Requisition", voucher) < 0.92
    )
    assert (
        match_catalogue_dt_by_vision_title(
            document_heading="Advance Requisition",
            document_types=[voucher],
        )
        is None
    )


def test_prompt_alone_does_not_match_unrelated_vision_title() -> None:
    """Do not treat shortTitle-in-own-prompt as evidence for an unrelated printed title."""
    expense = _dt(
        "DT-EXP",
        title="Expense bills",
        short_title="Expense bill",
        prompt=(
            "Expense bills will mostly be in the tenant's name with multiple line items "
            "showing the description of expenses."
        ),
    )
    assert score_definition_for_vision_title("TAX INVOICE", expense) < 0.92
