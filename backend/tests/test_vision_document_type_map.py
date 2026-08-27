"""Unit tests for vision heading/canonical → Rule Book DT mapping."""

from __future__ import annotations

import json

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.vision_document_type_map import (
    map_vision_label_to_document_type,
    map_vision_label_to_document_type_with_llm_fallback,
)
from app.services.prompt_registry.catalog import catalog_default_body


def _dt(
    *,
    code: str,
    title: str,
    short_title: str,
    klass: str = "Transactional",
    posting: str = "Yes",
    recognition_mode: str = "signals",
    recognition_signals: list[str] | None = None,
    priority: int = 100,
    enabled: bool = True,
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=title,
        shortTitle=short_title,
        klass=klass,
        posting=posting,
        recognitionMode=recognition_mode,
        recognitionSignals=recognition_signals or [],
        llmPrompt="",
        routeTarget="Vault",
        enabled=enabled,
        classifier={"enabled": False, "priority": priority, "confidence": 0.85},
    )


def test_map_commercial_invoice_to_transactional_dt() -> None:
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
        _dt(
            code="DT-02",
            title="Packing List",
            short_title="Packing List",
            klass="Non-transactional",
            posting="No",
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="COMMERCIAL INVOICE",
        canonical_document_type="Commercial Invoice",
        document_types=catalogue,
    )
    assert result.reason == "matched"
    assert result.code == "DT-07"
    assert result.confidence >= 0.82
    assert result.heading_kind == "commercial_invoice"


def test_map_tax_invoice_title_fallback() -> None:
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_mode="signals",
            recognition_signals=[],  # force title fallback
        ),
        _dt(
            code="DT-02",
            title="Packing List",
            short_title="Packing List",
            klass="Non-transactional",
            posting="No",
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=catalogue,
    )
    assert result.reason == "matched"
    assert result.code == "DT-07"
    assert result.heading_kind == "tax_invoice"


def test_map_packing_list_to_supporting_dt() -> None:
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
        _dt(
            code="DT-02",
            title="Packing List",
            short_title="Packing List",
            klass="Non-transactional",
            posting="No",
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="PACKING LIST",
        canonical_document_type="Packing List",
        document_types=catalogue,
    )
    assert result.reason == "matched"
    assert result.code == "DT-02"
    assert result.heading_kind == "packing_list"


def test_map_unknown_heading_no_kind() -> None:
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="HANDOVER SLIP",
        canonical_document_type="Handover Slip",
        document_types=catalogue,
    )
    assert result.code is None
    assert result.reason == "no_kind"


def test_map_below_threshold_when_catalogue_unrelated() -> None:
    catalogue = [
        _dt(
            code="DT-16",
            title="Contract",
            short_title="Contract",
            klass="Non-transactional",
            posting="No",
            recognition_signals=[],
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=catalogue,
    )
    assert result.code is None
    assert result.reason in {"below_threshold", "no_kind", "no_dt_for_role_invoice"}
    # Kind is inferred; score against Contract should fail threshold or role filter.
    if result.reason == "below_threshold":
        assert result.heading_kind == "tax_invoice"
    if result.reason == "no_dt_for_role_invoice":
        assert result.heading_kind == "tax_invoice"


def test_map_ambiguous_when_two_close_scores() -> None:
    catalogue = [
        _dt(
            code="DT-A",
            title="Packing List A",
            short_title="Packing List",
            klass="Non-transactional",
            posting="No",
            priority=50,
        ),
        _dt(
            code="DT-B",
            title="Packing List B",
            short_title="Packing List",
            klass="Non-transactional",
            posting="No",
            priority=60,
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="PACKING LIST",
        canonical_document_type="Packing List",
        document_types=catalogue,
    )
    assert result.code is None
    assert result.reason == "ambiguous"
    assert result.runner_up_code is not None


def test_map_human_locked_skips_scoring() -> None:
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="PACKING LIST",
        canonical_document_type="Packing List",
        document_types=catalogue,
        human_locked_dt="DT-99",
    )
    assert result.reason == "human_locked"
    assert result.code == "DT-99"
    assert result.confidence == 1.0


def test_map_empty_catalogue() -> None:
    result = map_vision_label_to_document_type(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=[],
    )
    assert result.code is None
    assert result.reason == "empty_catalogue"


def test_dt_map_fallback_prompt_is_robust() -> None:
    body = catalog_default_body("vision.dt_map_fallback.system") or ""
    assert "NEVER invent a DT code" in body
    assert 'Prefer "" over a weak guess' in body or "Prefer \"\" over a weak guess" in body
    assert "SELF-CHECK BEFORE RETURNING" in body
    assert "catalogue[].code" in body
    assert "few_shot_examples" in body
    assert "human_confirmed_dt" in body
    assert "DESPATCH ADVICE" in body


@pytest.mark.asyncio
async def test_llm_fallback_not_called_when_rules_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    async def _boom(**_kwargs):
        called["n"] += 1
        raise AssertionError("LLM should not run when rules match")

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _boom,
    )
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
    ]
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="COMMERCIAL INVOICE",
        canonical_document_type="Commercial Invoice",
        document_types=catalogue,
    )
    assert result.reason == "matched"
    assert result.code == "DT-07"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_tenant_heading_learning_overrides_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact prior reviewer heading → DT wins over deterministic score."""
    llm_called = {"n": 0}

    async def _boom(**_kwargs):
        llm_called["n"] += 1
        raise AssertionError("LLM must not run when learning resolves")

    async def _fake_learn(_session, **_kwargs):
        return ("DT-06", 0.93)

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _boom,
    )
    monkeypatch.setattr(
        "app.services.classification.classification_learning_service.learned_document_type_for_heading",
        _fake_learn,
    )
    catalogue = [
        _dt(
            code="DT-04",
            title="Goods Received Note",
            short_title="GRN",
            klass="Non-transactional",
            posting="No",
            recognition_signals=["heading_grn"],
        ),
        _dt(
            code="DT-06",
            title="Delivery Note",
            short_title="DN",
            klass="Non-transactional",
            posting="No",
            recognition_signals=["heading_delivery_note"],
        ),
    ]
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="DESPATCH ADVICE",
        canonical_document_type="Despatch Advice",
        document_types=catalogue,
        session=object(),
        tenant_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000001"),
    )
    assert result.reason == "learning_matched"
    assert result.method == "tenant_heading_learning"
    assert result.code == "DT-06"
    assert llm_called["n"] == 0


@pytest.mark.asyncio
async def test_llm_fallback_passes_few_shots_and_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def _fake_chat(*, system, user, **_kwargs):
        captured["user"] = user
        return {
            "suggested_dt": "DT-16",
            "confidence": 0.88,
            "reasoning": "few-shot match",
        }

    monkeypatch.setattr(
        "app.services.extraction.azure_openai_client.chat_json_async",
        _fake_chat,
    )
    monkeypatch.setattr(
        "app.services.prompt_registry.service.resolve_system_prompt_text",
        lambda _key: "test prompt",
    )
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
        _dt(
            code="DT-16",
            title="Handover Slip",
            short_title="Handover",
            klass="Non-transactional",
            posting="No",
        ),
    ]
    from app.services.tenant.tenant_org_context import OrgContext

    org = OrgContext(
        legal_name="Highvolt Industries Pty Ltd",
        classification_hints="Outbound DN titles may say Despatch Advice",
        default_perspective="seller",
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="HANDOVER SLIP",
        canonical_document_type="Handover Slip",
        document_types=catalogue,
        org=org,
        few_shots=[
            {
                "document_heading": "HANDOVER SLIP",
                "human_confirmed_dt": "DT-16",
                "llm_suggested_dt": "DT-07",
                "note": "Reviewer corrected DT-07 → DT-16",
            }
        ],
    )
    assert result.reason == "llm_matched"
    assert result.code == "DT-16"
    # Azure rejects a non-string message content with a 400, so the payload must
    # already be serialised by the time it reaches the client.
    assert isinstance(captured["user"], str)
    sent = json.loads(captured["user"])
    assert sent["few_shot_examples"][0]["human_confirmed_dt"] == "DT-16"
    assert sent["tenant"]["legal_name"] == "Highvolt Industries Pty Ltd"
    assert "Despatch" in sent["tenant"]["classification_hints"]


@pytest.mark.asyncio
async def test_llm_fallback_accepts_catalogue_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_llm(**kwargs):
        from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult

        return VisionDocumentTypeMapResult(
            code="DT-16",
            confidence=0.91,
            heading_kind=kwargs.get("heading_kind"),
            reason="llm_matched",
            method="llm_catalogue_fallback",
            rule_reason=kwargs.get("rule_fail_reason"),
            llm_reasoning="Handover maps to ops supporting DT",
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _fake_llm,
    )
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
        _dt(
            code="DT-16",
            title="Handover Slip",
            short_title="Handover",
            klass="Non-transactional",
            posting="No",
        ),
    ]
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="HANDOVER SLIP",
        canonical_document_type="Handover Slip",
        document_types=catalogue,
    )
    assert result.reason == "llm_matched"
    assert result.code == "DT-16"
    assert result.method == "llm_catalogue_fallback"
    assert result.rule_reason == "no_kind"


@pytest.mark.asyncio
async def test_llm_fallback_rejects_invalid_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_chat(**_kwargs):
        return {
            "suggested_dt": "DT-FAKE",
            "confidence": 0.99,
            "reasoning": "invented",
        }

    monkeypatch.setattr(
        "app.services.extraction.azure_openai_client.chat_json_async",
        _fake_chat,
    )
    monkeypatch.setattr(
        "app.services.prompt_registry.service.resolve_system_prompt_text",
        lambda _key: "test prompt",
    )
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
    ]
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="HANDOVER SLIP",
        canonical_document_type="Handover Slip",
        document_types=catalogue,
    )
    assert result.code is None
    assert result.reason == "llm_rejected"
    assert result.method == "llm_catalogue_fallback"


@pytest.mark.asyncio
async def test_llm_fallback_rejects_low_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_chat(**_kwargs):
        return {
            "suggested_dt": "DT-07",
            "confidence": 0.2,
            "reasoning": "unsure",
        }

    monkeypatch.setattr(
        "app.services.extraction.azure_openai_client.chat_json_async",
        _fake_chat,
    )
    monkeypatch.setattr(
        "app.services.prompt_registry.service.resolve_system_prompt_text",
        lambda _key: "test prompt",
    )
    catalogue = [
        _dt(
            code="DT-07",
            title="Supplier Tax Invoice",
            short_title="Tax Invoice",
            recognition_signals=["heading_invoice"],
        ),
    ]
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="HANDOVER SLIP",
        canonical_document_type="Handover Slip",
        document_types=catalogue,
    )
    assert result.code is None
    assert result.reason == "llm_rejected"


@pytest.mark.asyncio
async def test_classifier_fallback_picks_po_goods_via_playbook_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """playbookProfile=po_goods → recommended has_po_reference; no prompt scraping."""
    from decimal import Decimal

    from app.models.invoice import Invoice, InvoiceStatus
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _boom(**_kwargs):
        raise AssertionError("LLM must not run when classifier resolves")

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _boom,
    )

    catalogue = [
        DocumentTypeDefinition(
            code="DT-07",
            title="PO-based goods invoice",
            shortTitle="PO Goods Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="Prose description only — matching must use playbook signals.",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="po_goods",
            classifier={"enabled": False, "priority": 40, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-08",
            title="Non-PO vendor invoice",
            shortTitle="Non-PO Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="Prose for non-PO invoice.",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="direct_expense",
            classifier={"enabled": False, "priority": 50, "confidence": 0.85},
        ),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="INVOICE",
        invoice_no="82507681",
        po_reference="PO-250742524",
        total=Decimal("18864.00"),
        vendor="Lexar Co., Limited",
        extracted_fields={"canonical_document_type": "Invoice"},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="INVOICE",
        canonical_document_type="Invoice",
        document_types=catalogue,
        invoice=inv,
    )
    assert result.code == "DT-07"
    assert result.reason == "classifier_matched"
    assert result.method == "config_classifier"


@pytest.mark.asyncio
async def test_signals_classifier_fallback_uses_has_po_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.models.invoice import Invoice, InvoiceStatus
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _boom(**_kwargs):
        raise AssertionError("LLM must not run when signals classifier resolves")

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _boom,
    )
    catalogue = [
        _dt(
            code="DT-07",
            title="PO-based goods invoice",
            short_title="PO Goods Invoice",
            recognition_signals=[
                "heading_invoice",
                "text_invoice",
                "has_po_reference",
            ],
            priority=40,
        ),
        _dt(
            code="DT-08",
            title="Non-PO vendor invoice",
            short_title="Non-PO Invoice",
            recognition_signals=["heading_invoice", "has_invoice_number"],
            priority=80,
        ),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="INVOICE",
        invoice_no="82507681",
        po_reference="PO-250742524",
        total=Decimal("18864.00"),
        vendor="Lexar",
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="INVOICE",
        canonical_document_type="Invoice",
        document_types=catalogue,
        invoice=inv,
    )
    assert result.code == "DT-07"
    assert result.reason == "classifier_matched"


def test_effective_signals_uses_playbook_recommended_identity() -> None:
    from app.services.classification.document_type_rule_engine import (
        effective_signals_mode_definition,
    )
    from app.services.classification.recognition_signal_registry import (
        PLAYBOOK_RECOMMENDED_IDENTITY,
    )

    defn = DocumentTypeDefinition(
        code="DT-07",
        title="PO-based goods invoice",
        shortTitle="PO Goods Invoice",
        klass="Transactional",
        posting="Yes",
        recognitionMode="prompt",
        recognitionSignals=[],
        llmPrompt="Any prose",
        routeTarget="Purchase Management",
        enabled=True,
        playbookProfile="po_goods",
        classifier={"enabled": False, "priority": 40, "confidence": 0.9},
    )
    effective = effective_signals_mode_definition(defn)
    assert effective is not None
    assert set(effective.recognition_signals) == set(
        PLAYBOOK_RECOMMENDED_IDENTITY["po_goods"]
    )
    assert "has_po_reference" in effective.recognition_signals
    assert effective.classifier.enabled is True


@pytest.mark.asyncio
async def test_llm_payload_includes_document_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def _fake_chat(*, system, user, **_kwargs):
        captured["user"] = user
        return {
            "suggested_dt": "DT-03",
            "confidence": 0.9,
            "reasoning": "summary says PO-backed supplier invoice",
        }

    monkeypatch.setattr(
        "app.services.extraction.azure_openai_client.chat_json_async",
        _fake_chat,
    )
    monkeypatch.setattr(
        "app.services.prompt_registry.service.resolve_system_prompt_text",
        lambda _key: "test prompt",
    )

    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult
    from app.tenant_ids import TESTING_TENANT_UUID

    def _ambiguous_rule(**_kwargs):
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind="tax_invoice",
            reason="ambiguous",
            method="heading_kind_score",
            runner_up_code="DT-03",
            runner_up_score=0.9,
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map.map_vision_label_to_document_type",
        _ambiguous_rule,
    )

    catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="Non-PO vendor invoice",
            shortTitle="Non-PO Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="standard_transactional",
            classifier={"enabled": False, "priority": 80, "confidence": 0.85},
        ),
        DocumentTypeDefinition(
            code="DT-03",
            title="PO-based goods invoice",
            shortTitle="PO Goods Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="po_goods",
            classifier={"enabled": False, "priority": 40, "confidence": 0.9},
        ),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="TAX INVOICE",
        extracted_fields={
            "canonical_document_type": "Tax Invoice",
            "document_summary": (
                "Supplier tax invoice against purchase order PO-TEST-001 "
                "addressed to the buyer."
            ),
            "document_role_hints": {
                "has_po_reference": "true",
                "has_invoice_number": "true",
                "is_supporting_only": "false",
            },
        },
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=catalogue,
        invoice=inv,
    )
    assert result.code == "DT-03"
    assert result.method == "llm_catalogue_fallback"
    sent = json.loads(captured["user"])
    assert "PO-TEST-001" in sent["document_summary"]
    assert sent["document_role_hints"]["has_po_reference"] == "true"


@pytest.mark.asyncio
async def test_ambiguous_with_summary_skips_generic_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguous Non-PO vs PO-goods must not lock Non-PO when summary is present."""
    classifier_calls = {"n": 0}

    async def _fake_llm(**kwargs):
        from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult

        assert "PO-TEST" in (kwargs.get("document_summary") or "")
        return VisionDocumentTypeMapResult(
            code="DT-03",
            confidence=0.92,
            heading_kind=kwargs.get("heading_kind"),
            reason="llm_matched",
            method="llm_catalogue_fallback",
            rule_reason=kwargs.get("rule_fail_reason"),
            llm_reasoning="summary prefers PO-based",
        )

    def _counting_classifier(**_kwargs):
        classifier_calls["n"] += 1
        from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult

        return VisionDocumentTypeMapResult(
            code="DT-01",
            confidence=0.85,
            heading_kind="tax_invoice",
            reason="classifier_matched",
            method="config_classifier",
            rule_reason="ambiguous",
        )

    def _ambiguous_rule(**_kwargs):
        from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult

        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind="tax_invoice",
            reason="ambiguous",
            method="heading_kind_score",
            runner_up_code="DT-03",
            runner_up_score=0.9,
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _fake_llm,
    )
    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map.map_vision_via_configured_classifiers",
        _counting_classifier,
    )
    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map.map_vision_label_to_document_type",
        _ambiguous_rule,
    )

    from app.models.invoice import Invoice, InvoiceStatus
    from app.tenant_ids import TESTING_TENANT_UUID

    catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="Non-PO vendor invoice",
            shortTitle="Non-PO Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="standard_transactional",
            classifier={"enabled": False, "priority": 80, "confidence": 0.85},
        ),
        DocumentTypeDefinition(
            code="DT-03",
            title="PO-based goods invoice",
            shortTitle="PO Goods Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="po_goods",
            classifier={"enabled": False, "priority": 40, "confidence": 0.9},
        ),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="TAX INVOICE",
        # No po_reference column — summary alone must drive LLM path
        extracted_fields={
            "document_summary": (
                "Supplier tax invoice for goods against PO-TEST-001."
            ),
            "document_role_hints": {"has_po_reference": "true"},
        },
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=catalogue,
        invoice=inv,
    )
    assert result.code == "DT-03"
    assert result.method == "llm_catalogue_fallback"
    assert classifier_calls["n"] == 0


def test_dt_map_fallback_prompt_mentions_summary() -> None:
    body = catalog_default_body("vision.dt_map_fallback.system") or ""
    assert "document_summary" in body
    assert "document_role_hints" in body
    assert "sales receipts" in body.lower() or "POS" in body


@pytest.mark.asyncio
async def test_employee_email_retail_receipt_forces_team_expense_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POS / sales-receipt shape must still get TE claim DT for employee email."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _should_not_call_llm(**_kwargs):
        raise AssertionError("LLM must not run when employee-channel TE is forced")

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _should_not_call_llm,
    )

    catalogue = [
        DocumentTypeDefinition(
            code="DT-03",
            title="PO-based goods invoice",
            shortTitle="PO Goods",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="po_goods",
            classifier={"enabled": False, "priority": 40, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-04",
            title="Employee expense claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
            classifier={"enabled": False, "priority": 50, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-05",
            title="Advance requisition",
            shortTitle="Advance",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="advance_requisition",
            classifier={"enabled": False, "priority": 55, "confidence": 0.9},
        ),
    ]
    employee = EmployeeMaster(
        id="e1",
        name="Ka",
        email="ka12122000@gmail.com",
        status="Active",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Family Floral Gift Shop",
        capture_source="email",
        email_sender="ka12122000@gmail.com",
        extracted_fields={
            "canonical_document_type": "Sales Receipt",
            "document_summary": (
                "Seller-issued retail POS sales receipt (cash) from a gift shop."
            ),
        },
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Family Floral Gift Shop",
        canonical_document_type="Sales Receipt",
        document_types=catalogue,
        invoice=inv,
        employees=[employee],
    )
    assert result.code == "DT-04"
    assert result.method == "te_employee_channel"
    assert result.reason == "employee_channel_forced"


@pytest.mark.asyncio
async def test_employee_email_payment_voucher_title_match_beats_channel_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confident catalogue title match (Payment Voucher) wins over te_employee_channel."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _should_not_call_llm(**_kwargs):
        raise AssertionError("LLM must not run when title match wins")

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _should_not_call_llm,
    )

    catalogue = [
        DocumentTypeDefinition(
            code="DT-04",
            title="Employee expense claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
        ),
        DocumentTypeDefinition(
            code="DT-05",
            title="Advance requisition",
            shortTitle="Advance",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="advance_requisition",
        ),
        DocumentTypeDefinition(
            code="DT-06",
            title="Payment Voucher",
            shortTitle="Payment Voucher",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="",
        ),
    ]
    employee = EmployeeMaster(
        id="e1",
        name="Khushi",
        email="ka12122000@gmail.com",
        status="Active",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Payment Voucher",
        capture_source="email",
        email_sender="ka12122000@gmail.com",
        extracted_fields={"canonical_document_type": "Payment Voucher"},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Payment Voucher",
        canonical_document_type="Payment Voucher",
        document_types=catalogue,
        invoice=inv,
        employees=[employee],
    )
    assert result.code == "DT-06"
    assert result.method == "catalogue_title_match"
    assert result.reason == "catalogue_title_matched"
    assert result.method != "te_employee_channel"


def test_team_expense_channel_force_sets_runner_up_from_prior_rule() -> None:
    from app.services.invoice.vision_document_type_map import (
        _team_expense_channel_map_result,
    )

    catalogue = [
        DocumentTypeDefinition(
            code="DT-04",
            title="Employee expense claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
        ),
    ]
    forced = _team_expense_channel_map_result(
        invoice=None,
        document_types=catalogue,
        heading_kind="sales_receipt",
        rule_reason="matched",
        prior_code="DT-06",
        prior_confidence=0.97,
    )
    assert forced is not None
    assert forced.code == "DT-04"
    assert forced.runner_up_code == "DT-06"
    assert forced.runner_up_score == 0.97


def _inv752_te_catalogue() -> list[DocumentTypeDefinition]:
    """Live posting-test TE family: claim vs advance vs expense-against-advance."""
    return [
        DocumentTypeDefinition(
            code="DT-08",
            title="Employee expense claim / reimbursement",
            shortTitle="Expense claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt=(
                "Employee expense claim for reimbursement: the staff member paid "
                "from their own pocket and is asking the company to pay them back. "
                "Headings include Expense Claim, Expense Claim Form."
            ),
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
        ),
        DocumentTypeDefinition(
            code="DT-09",
            title="Employee advance request",
            shortTitle="Advance request",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt=(
                "Employee advance request form: a staff member asking for money "
                "before any spending has happened. Headings include Advance Requisition."
            ),
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="standard_transactional",
            teamExpenseKind="advance_requisition",
        ),
        DocumentTypeDefinition(
            code="DT-10",
            title="Expense against advance",
            shortTitle="Expense against advance",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt=(
                "Employee expense settlement against an advance already drawn. "
                "Headings include Expense against advance."
            ),
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="standard_transactional",
            teamExpenseKind="expense_claim",
        ),
    ]


def _inv752_title_scores(heading: str) -> dict[str, float]:
    from app.services.classification.catalogue_title_match import (
        score_definition_for_vision_title,
    )

    return {
        row.code: score_definition_for_vision_title(heading, row)
        for row in _inv752_te_catalogue()
    }


def test_channel_force_picks_advance_dt_when_te_title_scores_tie() -> None:
    """Inv 752: Advance Requisition ties DT-09 and DT-10 inside the 0.05
    margin, so step 2 aborts. Force must still pick the advance DT.

    Tie-break is not a default-to-DT-09: it keeps the tied row whose
    teamExpenseKind matches infer_team_expense_kind_from_labels (here
    ``advance requisition`` → advance_requisition → DT-09).
    """
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import TEAM_EXPENSE_KIND_ADVANCE
    from app.services.classification.catalogue_title_match import (
        match_catalogue_dt_by_vision_title,
    )
    from app.services.invoice.vision_document_type_map import (
        _best_team_expense_dt_for_channel_force,
        _team_expense_channel_map_result,
    )
    from app.services.purchase.team_expense_kind_service import (
        infer_team_expense_kind_from_labels,
    )
    from app.tenant_ids import TESTING_TENANT_UUID

    catalogue = _inv752_te_catalogue()
    scores = _inv752_title_scores("Advance Requisition")
    assert scores["DT-09"] >= 0.94
    assert scores["DT-10"] >= 0.94
    assert abs(scores["DT-09"] - scores["DT-10"]) < 0.05
    assert (
        match_catalogue_dt_by_vision_title(
            document_heading="Advance Requisition",
            document_types=catalogue,
        )
        is None
    )
    assert (
        infer_team_expense_kind_from_labels(
            "Advance Requisition",
            "Cash Advance Requisition",
        )
        == TEAM_EXPENSE_KIND_ADVANCE
    )
    picked = _best_team_expense_dt_for_channel_force(
        catalogue,
        labels=["Advance Requisition", "Cash Advance Requisition"],
        preferred_kind=TEAM_EXPENSE_KIND_ADVANCE,
    )
    assert picked is not None
    assert picked.code == "DT-09"

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Advance Requisition",
        capture_source="email",
        email_sender="codevishnu321@gmail.com",
        extracted_fields={"canonical_document_type": "Cash Advance Requisition"},
    )
    forced = _team_expense_channel_map_result(
        invoice=inv,
        document_types=catalogue,
        heading_kind=None,
        rule_reason="no_kind",
        prior_code=None,
    )
    assert forced is not None
    assert forced.code == "DT-09"
    assert forced.method == "te_employee_channel"
    assert forced.reason == "employee_channel_forced"


def test_channel_force_picks_dt10_on_same_title_tie_when_kind_is_claim() -> None:
    """Same 0.94-class title scores as inv 752, opposite kind → DT-10.

    Proves the tie-break is content-directed, not a default that always
    prefers DT-09. A genuine expense-against-advance heading unique-matches
    DT-10 (see test below); this case is the actual 09/10 score tie with
    the settlement kind forced in, the mirror of the requisition kind.
    """
    from app.schemas.rule_book_config import TEAM_EXPENSE_KIND_CLAIM
    from app.services.invoice.vision_document_type_map import (
        _best_team_expense_dt_for_channel_force,
    )

    catalogue = _inv752_te_catalogue()
    scores = _inv752_title_scores("Advance Requisition")
    assert abs(scores["DT-09"] - scores["DT-10"]) < 0.05
    picked = _best_team_expense_dt_for_channel_force(
        catalogue,
        labels=["Advance Requisition"],
        preferred_kind=TEAM_EXPENSE_KIND_CLAIM,
    )
    assert picked is not None
    assert picked.code == "DT-10"


def test_channel_force_picks_expense_against_advance_dt() -> None:
    """Genuine DT-10 document: heading contains 'expense against advance'.

    That heading does *not* hit the 0.94/0.94 tie — DT-10 unique-matches at
    1.0 because the catalogue title is the same phrase. Force must still
    land on DT-10, not DT-08 (the other expense_claim row) or DT-09.
    """
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import TEAM_EXPENSE_KIND_CLAIM
    from app.services.classification.catalogue_title_match import (
        match_catalogue_dt_by_vision_title,
    )
    from app.services.invoice.vision_document_type_map import (
        _team_expense_channel_map_result,
    )
    from app.services.purchase.team_expense_kind_service import (
        infer_team_expense_kind_from_labels,
    )
    from app.tenant_ids import TESTING_TENANT_UUID

    catalogue = _inv752_te_catalogue()
    heading = "Expense against advance"
    scores = _inv752_title_scores(heading)
    assert scores["DT-10"] == 1.0
    # DT-09 still scores 0.94 because shortTitle "Advance request" cores to
    # "advance", which sits inside this heading. Margin 0.06 is enough for
    # step 2 to unique-match DT-10 — unlike "Advance Requisition", where
    # both rows stay inside the 0.05 tie band.
    assert scores["DT-10"] - scores["DT-09"] >= 0.05
    assert scores["DT-08"] < 0.92
    hit = match_catalogue_dt_by_vision_title(
        document_heading=heading,
        document_types=catalogue,
    )
    assert hit is not None
    assert hit[0].code == "DT-10"
    assert infer_team_expense_kind_from_labels(heading) == TEAM_EXPENSE_KIND_CLAIM

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading=heading,
        capture_source="email",
        email_sender="codevishnu321@gmail.com",
        extracted_fields={"canonical_document_type": heading},
    )
    forced = _team_expense_channel_map_result(
        invoice=inv,
        document_types=catalogue,
        heading_kind="expense_against_advance",
        rule_reason="matched",
        prior_code=None,
    )
    assert forced is not None
    assert forced.code == "DT-10"
    assert forced.method == "te_employee_channel"


def test_heading_kind_scorer_distinguishes_advance_vs_against_advance() -> None:
    """Step 4 / PDF-segment classify share HEADING_KIND_TOKENS for TE forms."""
    from app.services.classification.segment_heading_classification import (
        HEADING_KIND_TOKENS,
        score_document_type_for_heading,
    )
    from app.services.extraction.document_heading_utils import infer_page_document_kind

    catalogue = _inv752_te_catalogue()
    dt09, dt10 = catalogue[1], catalogue[2]
    assert "advance_requisition" in HEADING_KIND_TOKENS
    assert "expense_against_advance" in HEADING_KIND_TOKENS
    assert infer_page_document_kind("Advance Requisition\nName: Khushi") == (
        "advance_requisition"
    )
    assert infer_page_document_kind("Expense against advance\nName: Khushi") == (
        "expense_against_advance"
    )
    assert infer_page_document_kind("Cash Advance Requisition\nForm 3182") == (
        "advance_requisition"
    )
    advance_scores = {
        row.code: score_document_type_for_heading(row, "advance_requisition")
        for row in catalogue
    }
    against_scores = {
        row.code: score_document_type_for_heading(row, "expense_against_advance")
        for row in catalogue
    }
    assert advance_scores["DT-09"] >= 0.82
    assert advance_scores["DT-09"] - advance_scores["DT-10"] >= 0.05
    assert against_scores["DT-10"] >= 0.82
    assert against_scores["DT-10"] - against_scores["DT-09"] >= 0.05
    assert dt09.code == "DT-09"
    assert dt10.code == "DT-10"


@pytest.mark.asyncio
async def test_employee_email_advance_requisition_does_not_default_to_claim() -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.tenant_ids import TESTING_TENANT_UUID

    employee = EmployeeMaster(
        id="e1",
        name="Vishnu",
        email="codevishnu321@gmail.com",
        status="Active",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Advance Requisition",
        capture_source="email",
        email_sender="codevishnu321@gmail.com",
        extracted_fields={"canonical_document_type": "Cash Advance Requisition"},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Advance Requisition",
        canonical_document_type="Cash Advance Requisition",
        document_types=_inv752_te_catalogue(),
        invoice=inv,
        employees=[employee],
    )
    assert result.code == "DT-09"
    assert result.method == "te_employee_channel"


@pytest.mark.asyncio
async def test_employee_email_expense_against_advance_picks_dt10() -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.tenant_ids import TESTING_TENANT_UUID

    employee = EmployeeMaster(
        id="e1",
        name="Vishnu",
        email="codevishnu321@gmail.com",
        status="Active",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Expense against advance",
        capture_source="email",
        email_sender="codevishnu321@gmail.com",
        extracted_fields={"canonical_document_type": "Expense against advance"},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Expense against advance",
        canonical_document_type="Expense against advance",
        document_types=_inv752_te_catalogue(),
        invoice=inv,
        employees=[employee],
    )
    assert result.code == "DT-10"
    # Step 2 unique-matches this heading (1.0 vs 0.94), so the employee
    # force never runs. That is the correct path — not a swapped default.
    assert result.method == "catalogue_title_match"


def test_step4_heading_kind_picks_advance_when_title_match_ties() -> None:
    """Upload / no employee-channel: step 4 must not be no_kind on this title."""
    result = map_vision_label_to_document_type(
        document_heading="Advance Requisition",
        canonical_document_type="Cash Advance Requisition",
        document_types=_inv752_te_catalogue(),
    )
    assert result.code == "DT-09"
    assert result.heading_kind == "advance_requisition"
    assert result.method == "heading_kind_score"
    assert result.reason == "matched"


def test_step2_unique_matches_expense_against_advance() -> None:
    result = map_vision_label_to_document_type(
        document_heading="Expense against advance",
        canonical_document_type="Expense against advance",
        document_types=_inv752_te_catalogue(),
    )
    assert result.code == "DT-10"
    assert result.method == "catalogue_title_match"


@pytest.mark.asyncio
async def test_employee_whatsapp_advance_heading_picks_advance_dt() -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.tenant_ids import TESTING_TENANT_UUID

    catalogue = [
        DocumentTypeDefinition(
            code="DT-04",
            title="Employee expense claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
        ),
        DocumentTypeDefinition(
            code="DT-05",
            title="Advance requisition",
            shortTitle="Advance",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="advance_requisition",
        ),
    ]
    employee = EmployeeMaster(
        id="e1",
        name="Priya",
        email="priya@acme.com",
        whatsapp_number="+61412345678",
        status="Active",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Advance request form",
        capture_source="whatsapp",
        email_sender="+61412345678",
        extracted_fields={"document_summary": "Employee advance request for travel."},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Advance request form",
        canonical_document_type="",
        document_types=catalogue,
        invoice=inv,
        employees=[employee],
    )
    assert result.code == "DT-05"
    # Title match runs before channel force; either path must land on Advance.
    assert result.method in {"te_employee_channel", "catalogue_title_match"}


@pytest.mark.asyncio
async def test_upload_does_not_force_team_expense_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _fake_llm(**_kwargs):
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.2,
            heading_kind=None,
            reason="llm_empty",
            method="llm_catalogue_fallback",
            rule_reason="no_kind",
            llm_reasoning="no match",
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _fake_llm,
    )

    catalogue = [
        DocumentTypeDefinition(
            code="DT-04",
            title="Employee expense claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
        ),
    ]
    employee = EmployeeMaster(
        id="e1", name="Ka", email="ka@acme.com", status="Active"
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Family Floral Gift Shop",
        capture_source="upload",
        email_sender="ka@acme.com",
        extracted_fields={"canonical_document_type": "Sales Receipt"},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Family Floral Gift Shop",
        canonical_document_type="Sales Receipt",
        document_types=catalogue,
        invoice=inv,
        employees=[employee],
    )
    assert result.code is None
    assert result.method != "te_employee_channel"


def _employee_te_catalogue() -> list[DocumentTypeDefinition]:
    return [
        DocumentTypeDefinition(
            code="DT-03",
            title="PO-based goods invoice",
            shortTitle="PO Goods",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="po_goods",
            classifier={"enabled": False, "priority": 40, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-04",
            title="Employee expense claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
            classifier={"enabled": False, "priority": 50, "confidence": 0.9},
        ),
    ]


@pytest.mark.asyncio
async def test_employee_email_po_hint_skips_team_expense_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content-based skip: PO structure wins over employee-channel force."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _fake_llm(**_kwargs):
        return VisionDocumentTypeMapResult(
            code="DT-03",
            confidence=0.82,
            heading_kind="tax_invoice",
            reason="llm_matched",
            method="llm_catalogue_fallback",
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _fake_llm,
    )
    events: list[str] = []

    async def _capture(_session, event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("app.services.audit.audit_service.log_event", _capture)

    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    inv = Invoice(
        id=401,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="TAX INVOICE",
        capture_source="email",
        email_sender="priya@acme.com",
        extracted_fields={
            "canonical_document_type": "Tax Invoice",
            "document_role_hints": {
                "has_po_reference": "true",
                "has_invoice_number": "true",
            },
        },
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=_employee_te_catalogue(),
        invoice=inv,
        employees=[employee],
        session=object(),
    )
    assert result.method != "te_employee_channel"
    assert result.reason != "employee_channel_forced"
    assert "vision_te_channel_skipped_commercial" in events
    assert "vision_te_channel_forced" not in events


@pytest.mark.asyncio
async def test_employee_email_invoice_number_alone_still_forces_te(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receipt numbers are not commercial — keep the employee-channel force."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _should_not_call_llm(**_kwargs):
        raise AssertionError("LLM must not run when employee-channel TE is forced")

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _should_not_call_llm,
    )
    events: list[str] = []

    async def _capture(_session, event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("app.services.audit.audit_service.log_event", _capture)

    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    inv = Invoice(
        id=402,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Family Floral Gift Shop",
        capture_source="email",
        email_sender="priya@acme.com",
        extracted_fields={
            "canonical_document_type": "Sales Receipt",
            "document_role_hints": {"has_invoice_number": "true"},
        },
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="Family Floral Gift Shop",
        canonical_document_type="Sales Receipt",
        document_types=_employee_te_catalogue(),
        invoice=inv,
        employees=[employee],
        session=object(),
    )
    assert result.code == "DT-04"
    assert result.method == "te_employee_channel"
    assert result.reason == "employee_channel_forced"
    assert "vision_te_channel_forced" in events
    assert "vision_te_channel_skipped_commercial" not in events


@pytest.mark.asyncio
async def test_employee_email_credit_note_hint_skips_te_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _fake_llm(**_kwargs):
        return VisionDocumentTypeMapResult(
            code="DT-03",
            confidence=0.7,
            heading_kind="credit_note",
            reason="llm_matched",
            method="llm_catalogue_fallback",
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _fake_llm,
    )
    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="CREDIT NOTE",
        capture_source="email",
        email_sender="priya@acme.com",
        extracted_fields={"document_role_hints": {"is_credit_note": "true"}},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="CREDIT NOTE",
        canonical_document_type="Credit Note",
        document_types=_employee_te_catalogue(),
        invoice=inv,
        employees=[employee],
    )
    assert result.method != "te_employee_channel"


@pytest.mark.asyncio
async def test_employee_email_so_hint_skips_te_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.schemas.rule_book_config import EmployeeMaster
    from app.services.invoice.vision_document_type_map import VisionDocumentTypeMapResult
    from app.tenant_ids import TESTING_TENANT_UUID

    async def _fake_llm(**_kwargs):
        return VisionDocumentTypeMapResult(
            code="DT-03",
            confidence=0.7,
            heading_kind="tax_invoice",
            reason="llm_matched",
            method="llm_catalogue_fallback",
        )

    monkeypatch.setattr(
        "app.services.invoice.vision_document_type_map._llm_pick_catalogue_dt",
        _fake_llm,
    )
    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="TAX INVOICE",
        capture_source="email",
        email_sender="priya@acme.com",
        extracted_fields={"document_role_hints": {"has_so_reference": "true"}},
    )
    result = await map_vision_label_to_document_type_with_llm_fallback(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=_employee_te_catalogue(),
        invoice=inv,
        employees=[employee],
    )
    assert result.method != "te_employee_channel"

def test_advance_requisition_catalogue_title_beats_payment_voucher_on_upload() -> None:
    """Staging-style mix-up: vision title matches Rule Book Advance row, not Payment Voucher."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.invoice.vision_document_type_map import map_vision_label_to_document_type
    from app.tenant_ids import TESTING_TENANT_UUID

    catalogue = [
        DocumentTypeDefinition(
            code="DT-06",
            title="Payment Voucher",
            shortTitle="Payment Voucher",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt=(
                "Payment Voucher for settled employee or vendor payments. "
                "Cash / bank payment evidence with approver signatures. "
                "Do not classify Advance Requisition or Advance Request."
            ),
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="expense_claim",
        ),
        DocumentTypeDefinition(
            code="DT-05",
            title="Advance requisition",
            shortTitle="Advance Requisition",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt=(
                "Advance Requisition / Advance Request for employee cash advances. "
                "Headings include Advance Requisition. Do not classify Payment Voucher."
            ),
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="advance_requisition",
        ),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="Advance Requisition",
        capture_source="upload",
    )
    result = map_vision_label_to_document_type(
        document_heading="Advance Requisition",
        canonical_document_type="",
        document_types=catalogue,
        invoice=inv,
    )
    assert result.heading_kind is None
    assert result.code == "DT-05"
    assert result.method == "catalogue_title_match"
    assert result.confidence >= 0.92


def test_proforma_signal_does_not_match_advance_request() -> None:
    from app.services.classification.recognition_signal_registry import SIGNAL_CONDITIONS

    import re

    text_pat = re.compile(str(SIGNAL_CONDITIONS["text_proforma"]["value"]))
    assert text_pat.search("PROFORMA INVOICE")
    assert not text_pat.search("Advance request for travel")
    assert not text_pat.search("Advance Requisition\nAmount 20000")

    adv_pat = re.compile(str(SIGNAL_CONDITIONS["text_advance_requisition"]["value"]))
    assert adv_pat.search("Advance Requisition")
    assert adv_pat.search("staff advance request")
