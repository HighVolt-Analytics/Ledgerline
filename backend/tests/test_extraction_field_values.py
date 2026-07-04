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
    custom_extraction_field_descriptors,
    custom_extraction_field_keys,
    custom_extraction_field_keys_for_dt,
    enrich_parsed_from_ocr,
    harvest_custom_fields_from_llm_raw,
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
        oneLine="test",
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


def test_enrich_parsed_from_ocr_fills_missing_invoice_no() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nInvoice No: INV-2026-42\nVendor: Acme Pty Ltd",
        text_length=60,
    )
    parsed = InvoiceData(document_text=ocr.text)
    enriched = enrich_parsed_from_ocr(parsed, ocr)
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
    enriched = enrich_parsed_from_ocr(parsed, ocr)
    assert enriched.extracted_fields.get("permit_no") == "OD6E379991N"


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
        custom_keys=["contract_party"],
    )
    import json

    data = json.loads(payload)
    assert data["custom_extraction_fields"] == ["contract_party"]
    assert data["custom_extraction_field_descriptors"] == [
        {"key": "contract_party", "label": "Contract Party"}
    ]


def test_normalize_llm_raw_harvests_custom_field_with_keys() -> None:
    normalized = _normalize_llm_raw(
        {"contract_party": "Buyer Co", "extracted_fields": {}},
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
