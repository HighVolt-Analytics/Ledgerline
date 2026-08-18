"""Custom and document_heading extraction field persistence."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.document_type_field_checks import field_is_present
from app.services.classification.document_type_rule_engine import build_document_classifier_context
from app.services.extraction.extraction_field_values import (
    apply_parsed_extraction_fields,
    build_extraction_field_manifest,
    build_field_ocr_snippets,
    custom_extraction_field_descriptors,
    custom_extraction_field_keys,
    custom_extraction_field_keys_for_dt,
    effective_extraction_field_keys_for_dt,
    enrich_parsed_from_ocr,
    expand_extraction_keys_for_llm,
    harvest_custom_fields_from_llm_raw,
    merge_gap_fill_into_parsed,
    missing_configured_extraction_keys,
    non_canonical_extraction_keys,
    normalize_extracted_fields_map,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.extraction.llm_document_service import (
    _normalize_llm_raw,
    build_llm_user_payload,
    llm_result_to_invoice_data,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-90",
        title="Contract",
        shortTitle="Contract",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Vault",
        classifier=DocumentTypeClassifier(),
        extraction_fields=["vendor", "contract_party"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_custom_extraction_field_keys_filters_canonical() -> None:
    keys = custom_extraction_field_keys([_definition()])
    assert keys == ["contract_party"]


def test_custom_extraction_field_keys_for_dt_scoped() -> None:
    other = _definition(code="DT-01", extraction_fields=["vendor", "project_code"])
    contract = _definition(code="DT-90", extraction_fields=["vendor", "contract_party"])
    assert custom_extraction_field_keys_for_dt([other, contract], "DT-90") == ["contract_party"]
    assert custom_extraction_field_keys_for_dt([other, contract], "DT-01") == ["project_code"]


def test_custom_extraction_field_keys_for_dt_includes_required_custom() -> None:
    other = _definition(code="DT-01", extraction_fields=["vendor", "project_code"])
    permit = _definition(
        code="DT-02",
        extraction_fields=["vendor", "permit_no", "consignment_ref"],
        required_fields=["vendor", "permit_no", "consignment_ref"],
    )
    keys = custom_extraction_field_keys_for_dt([other, permit], "DT-02")
    assert keys == ["permit_no", "consignment_ref"]


def test_effective_extraction_field_keys_for_dt_merges_required() -> None:
    permit = _definition(
        code="DT-02",
        extraction_fields=["vendor", "permit_no", "consignment_ref"],
        required_fields=["consignment_ref"],
    )
    keys = effective_extraction_field_keys_for_dt([permit], "DT-02")
    assert keys == ["vendor", "permit_no", "consignment_ref"]


def test_effective_extraction_field_keys_empty_uses_shipped_template_defaults() -> None:
    permit = _definition(
        code="ORG-02",
        matrix_template_code="DT-02",
        extraction_fields=[],
        required_fields=[],
    )
    keys = effective_extraction_field_keys_for_dt([permit], "ORG-02")
    assert "permit_no" in keys
    assert "vendor" in keys


def test_effective_extraction_field_keys_custom_without_config_returns_empty() -> None:
    """Non-transactional DT with no configured fields stays empty (no invoice dump)."""
    custom = _definition(
        code="ORG-99",
        extraction_fields=[],
        required_fields=[],
    )
    assert effective_extraction_field_keys_for_dt([custom], "ORG-99") == []


def test_effective_extraction_field_keys_transactional_empty_uses_playbook_or_commercial() -> None:
    """Transactional DT with empty extraction_fields still gets a commercial key universe."""
    custom = _definition(
        code="ORG-88",
        title="Custom goods invoice",
        shortTitle="Custom goods",
        klass="Transactional",
        posting="Yes",
        routeTarget="Purchase Management",
        playbook_profile="standard_transactional",
        extraction_fields=[],
        required_fields=[],
    )
    keys = effective_extraction_field_keys_for_dt([custom], "ORG-88")
    assert "vendor" in keys
    assert "invoice_no" in keys
    assert "total" in keys
    assert "line_items" in keys


def test_effective_extraction_field_keys_unknown_code_returns_empty() -> None:
    assert effective_extraction_field_keys_for_dt([_definition()], "MISSING") == []


def test_expand_extraction_keys_for_llm_expands_bank_details() -> None:
    expanded = expand_extraction_keys_for_llm(["vendor", "bank_details"])
    assert expanded == ["vendor", "bank_bsb", "bank_account", "bank_name"]


def test_non_canonical_extraction_keys_filters_presets() -> None:
    keys = non_canonical_extraction_keys(["vendor", "permit_no", "total"])
    assert keys == ["permit_no"]


def test_harvest_custom_fields_from_top_level_llm_raw() -> None:
    harvested = harvest_custom_fields_from_llm_raw(
        {
            "contract_party": "Permagen Planting Land Pty Ltd",
            "invoice_no": "INV-1",
            "extracted_fields": {"project_code": "PO-MKT"},
        },
        custom_keys=["contract_party", "project_code"],
    )
    assert harvested["contract_party"] == "Permagen Planting Land Pty Ltd"
    assert harvested["project_code"] == "PO-MKT"


def test_harvest_configured_canonical_account_code_from_llm_raw() -> None:
    harvested = harvest_custom_fields_from_llm_raw(
        {
            "account_code": "6100",
            "vendor": "Acme Pty Ltd",
            "extracted_fields": {"account_name": "Travel Expense"},
        },
        selected_keys=["vendor", "account_code", "account_name"],
    )
    assert harvested["account_code"] == "6100"
    assert harvested["account_name"] == "Travel Expense"
    assert "vendor" not in harvested


def test_enrich_parsed_from_ocr_fills_configured_account_code_and_custom() -> None:
    ocr = OcrArtifact(
        success=True,
        text=(
            "Vendor: Acme Pty Ltd\nTAX INVOICE\n"
            "PO: 12345\nAccount Code: 6100\nProject Code: PRJ-42\n"
        ),
        text_length=80,
    )
    parsed = InvoiceData(document_text=ocr.text)
    invoice_dt = _definition(
        code="DT-01",
        extraction_fields=["vendor", "po_reference", "account_code", "project_code"],
    )
    enriched = enrich_parsed_from_ocr(parsed, ocr, dt_definition=invoice_dt)
    assert enriched.po_reference == "12345"
    assert enriched.extracted_fields.get("account_code") == "6100"
    assert enriched.extracted_fields.get("project_code") == "PRJ-42"


def test_effective_extraction_fields_merges_required_fields() -> None:
    from app.services.classification.document_type_playbook_service import effective_extraction_fields

    permit = _definition(
        code="DT-02",
        extraction_fields=["vendor", "permit_no", "consignment_ref"],
        required_fields=["consignment_ref"],
    )
    keys = effective_extraction_fields(permit)
    assert "consignment_ref" in keys
    assert "permit_no" in keys


def test_enrich_parsed_from_ocr_fills_missing_invoice_no() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nInvoice No: INV-2026-42\nVendor: Acme Pty Ltd",
        text_length=60,
    )
    parsed = InvoiceData(document_text=ocr.text)
    invoice_dt = _definition(
        code="DT-01",
        extraction_fields=["vendor", "invoice_no"],
    )
    enriched = enrich_parsed_from_ocr(parsed, ocr, dt_definition=invoice_dt)
    assert enriched.invoice_no == "INV-2026-42"


def test_normalize_extracted_fields_map() -> None:
    assert normalize_extracted_fields_map(
        {"Contract_Party": " Acme ", "bad-key": "x", "vendor": "V"}
    ) == {"contract_party": "Acme", "vendor": "V"}


def test_llm_result_maps_extracted_fields() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-90",
        confidence=0.9,
        document_heading="MASTER SERVICES AGREEMENT",
        raw={
            "contract_party": "Permagen Planting Land Pty Ltd",
            "extracted_fields": {},
        },
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(success=True, text="MASTER SERVICES AGREEMENT\nValue 100", text_length=30),
        custom_keys=["contract_party"],
    )
    assert parsed.document_heading == "MASTER SERVICES AGREEMENT"
    assert parsed.extracted_fields["contract_party"] == "Permagen Planting Land Pty Ltd"


def test_enrich_parsed_from_ocr_harvests_permit_no() -> None:
    ocr = OcrArtifact(
        success=True,
        text="CARGO CLEARANCE PERMIT\nPermit No: OD6E379991N",
        text_length=40,
    )
    parsed = InvoiceData(document_text=ocr.text)
    permit_dt = _definition(
        code="DT-02",
        extraction_fields=["permit_no", "document_text"],
    )
    enriched = enrich_parsed_from_ocr(parsed, ocr, dt_definition=permit_dt)
    assert enriched.extracted_fields.get("permit_no") == "OD6E379991N"


def test_enrich_parsed_from_ocr_skips_invoice_no_when_not_configured() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nInvoice No: INV-2026-42\nVendor: Acme Pty Ltd",
        text_length=60,
    )
    parsed = InvoiceData(document_text=ocr.text)
    permit_dt = _definition(
        code="DT-02",
        extraction_fields=["vendor", "permit_no"],
    )
    enriched = enrich_parsed_from_ocr(parsed, ocr, dt_definition=permit_dt)
    assert enriched.invoice_no is None


def test_apply_parsed_extraction_fields_persists_on_invoice() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    parsed = InvoiceData(
        vendor="Acme",
        total=Decimal("100"),
        document_heading="Finance Contract",
        extracted_fields={"contract_party": "Buyer Co"},
        document_text="Finance Contract\nBuyer Co",
    )
    apply_parsed_extraction_fields(inv, parsed)
    assert inv.document_heading == "Finance Contract"
    assert inv.extracted_fields == {
        "contract_party": "Buyer Co",
        "document_heading": "Finance Contract",
    }


def test_apply_parsed_extraction_fields_preserve_keeps_clerk_total() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="USD",
        document_heading="TAX-CUM-COMMERCIAL INVOICE",
        extracted_fields={"total": "16000.00", "vendor": "Classic Enterprise"},
    )
    parsed = InvoiceData(
        vendor="Classic Enterprise",
        total=Decimal("0"),
        document_heading="TAX-CUM-COMMERCIAL INVOICE",
        extracted_fields={"total": "0.0", "vendor": "Classic Enterprise"},
    )
    apply_parsed_extraction_fields(inv, parsed, preserve_existing=True)
    assert inv.extracted_fields["total"] == "16000.00"
    assert inv.document_heading == "TAX-CUM-COMMERCIAL INVOICE"


def test_field_is_present_reads_custom_extracted_field() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        extracted_fields={"contract_party": "Clima Solutions Pty Ltd"},
    )
    parsed = InvoiceData(document_text="Contract")
    ctx = build_document_classifier_context(invoice=inv, parsed=parsed)
    assert field_is_present(
        "contract_party",
        invoice=inv,
        parsed=parsed,
        ctx=ctx,
    )


def test_custom_extraction_field_descriptors_include_label() -> None:
    descriptors = custom_extraction_field_descriptors(["contract_party", "vendor"])
    assert descriptors == [{"key": "contract_party", "label": "Contract Party"}]


def test_build_llm_user_payload_includes_descriptors() -> None:
    from app.services.tenant.tenant_org_context import OrgContext

    payload = build_llm_user_payload(
        ocr=OcrArtifact(success=True, text="Contract Party: Acme", text_length=20),
        org=OrgContext(),
        document_types=[_definition()],
        selected_keys=["vendor", "contract_party"],
    )
    import json

    data = json.loads(payload)
    assert data["custom_extraction_fields"] == ["contract_party"]
    assert data["custom_extraction_field_descriptors"] == [
        {"key": "contract_party", "label": "Contract Party"}
    ]
    assert data["ocr"]["text_excerpt"] == "Contract Party: Acme"
    assert data["extraction_field_manifest"]


def test_build_extraction_field_manifest_includes_vendor_label() -> None:
    manifest = build_extraction_field_manifest(["vendor", "contract_party"])
    labels = {row["key"]: row["label"] for row in manifest}
    assert labels["vendor"] == "Vendor"
    assert labels["contract_party"] == "Contract Party"


def test_build_llm_user_payload_includes_invoice_fields() -> None:
    from app.services.tenant.tenant_org_context import OrgContext

    ocr = OcrArtifact(
        success=True,
        text="Invoice body",
        text_length=12,
        payload_json={
            "invoice_fields": {"vendor": "Acme", "invoice_no": "INV-9"},
            "document_heading": "Tax Invoice",
        },
    )
    import json

    data = json.loads(
        build_llm_user_payload(
            ocr=ocr,
            org=OrgContext(),
            document_types=[_definition()],
            confirmed_dt="DT-90",
            selected_keys=["vendor", "invoice_no"],
        )
    )
    assert data["ocr"]["scalar_fields_source"] == "azure_di"
    assert data["ocr"]["azure_di_scalar_fields"]["vendor"]["value"] == "Acme"
    assert data["ocr"]["azure_di_scalar_fields"]["invoice_no"]["value"] == "INV-9"
    assert "invoice_fields" not in data
    assert data["ocr"]["document_heading"] == "Tax Invoice"


def test_build_structure_extract_prompts_uses_ocr_payload() -> None:
    from app.services.extraction.llm_document_service import build_structure_extract_prompts
    from app.services.tenant.tenant_org_context import OrgContext

    ocr = OcrArtifact(
        success=True,
        text="Vendor: Acme\nTotal: 50",
        text_length=18,
        layout_kv={"Total": "50"},
    )
    system, user = build_structure_extract_prompts(
        ocr=ocr,
        org=OrgContext(),
        document_types=[_definition()],
        confirmed_dt="DT-01",
    )
    import json

    assert "structure" in system.lower() or "ocr" in system.lower()
    data = json.loads(user)
    assert data["confirmed_dt"] == "DT-01"
    assert "Vendor: Acme" in data["ocr"]["text_excerpt"]
    assert data["ocr"]["layout_kv"] == {"Total": "50"}


def test_normalize_llm_raw_harvests_custom_field_with_keys() -> None:
    normalized = _normalize_llm_raw(
        {"contract_party": "Buyer Co", "extracted_fields": {}},
        selected_keys=["contract_party"],
        custom_keys=["contract_party"],
    )
    assert normalized["extracted_fields"]["contract_party"] == "Buyer Co"


def test_enrich_parsed_from_ocr_harvests_contract_party() -> None:
    ocr = OcrArtifact(
        success=True,
        text="FINANCE CONTRACT\nContract Party: Permagen Planting Land Pty Ltd",
        text_length=55,
    )
    parsed = InvoiceData(document_text=ocr.text)
    enriched = enrich_parsed_from_ocr(parsed, ocr, dt_definition=_definition())
    assert enriched.extracted_fields.get("contract_party") == "Permagen Planting Land Pty Ltd"


def test_build_field_ocr_snippets_finds_account_code_context() -> None:
    text = "Header line\nVendor: Acme\nAccount Code: 4100\nFooter"
    snippets = build_field_ocr_snippets(text, ["account_code"])
    assert "4100" in snippets["account_code"]
    assert "Account Code" in snippets["account_code"]


def test_build_field_ocr_snippets_money_uses_footer_tail() -> None:
    padding = "intro " * 200
    text = f"{padding}\nBalance due\n1,234.56"
    snippets = build_field_ocr_snippets(text, ["total"])
    assert "Balance due" in snippets["total"]
    assert "1,234.56" in snippets["total"]


def test_missing_configured_extraction_keys_returns_empty_fields() -> None:
    parsed = InvoiceData(vendor="Acme", document_text="Vendor: Acme")
    missing = missing_configured_extraction_keys(
        ["vendor", "invoice_no", "account_code"],
        parsed=parsed,
    )
    assert "vendor" not in missing
    assert "invoice_no" in missing
    assert "account_code" in missing


def test_merge_gap_fill_preserves_existing_invoice_no() -> None:
    ocr_text = "Invoice No: INV-100\nVendor: Acme"
    parsed = InvoiceData(invoice_no="INV-100", document_text=ocr_text)
    gap = InvoiceData(invoice_no="INV-999", document_text=ocr_text)
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["invoice_no"],
        ocr_text=ocr_text,
    )
    assert result.parsed.invoice_no == "INV-100"
    assert result.filled == ()
