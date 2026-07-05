"""Tests for bank detail extraction and validation."""

from app.services.extraction.field_grounding_service import (
    merge_bank_fields,
    validate_bank_account,
    validate_bank_bsb,
    value_grounded_in_ocr,
)
from app.services.extraction.pdf_parser import parse_text_fields


def test_phone_fragment_not_extracted_as_bsb() -> None:
    text = """
    Catamorphic Co DBA LaunchDarkly
    Phone: +1 415-579-3275
    Email: support@launchdarkly.com
    Total: $156.00
    """
    fields = parse_text_fields(text)
    assert fields.get("bank_bsb") is None
    assert fields.get("bank_account") is None
    assert merge_bank_fields(
        llm_bsb=None,
        llm_account=None,
        regex_bsb=fields.get("bank_bsb"),
        regex_account=fields.get("bank_account"),
        ocr_text=text,
    ) == (None, None)


def test_labeled_bsb_and_account_extracted() -> None:
    text = """
    Payment details
    BSB: 123-456
    Account No: 12345678
    """
    fields = parse_text_fields(text)
    bsb, account = merge_bank_fields(
        llm_bsb=fields.get("bank_bsb"),
        llm_account=fields.get("bank_account"),
        regex_bsb=fields.get("bank_bsb"),
        regex_account=fields.get("bank_account"),
        ocr_text=text,
    )
    assert bsb == "123-456"
    assert account == "12345678"
    assert validate_bank_bsb(bsb, text) == "123-456"
    assert validate_bank_account(account, text) == "12345678"


def test_gstin_digit_fragment_not_accepted_as_abn_grounding() -> None:
    ocr = "GSTIN: 29ABLFM0589J1ZM\nVendor: Marketing Panthers"
    hallucinated = "29058910589"
    assert value_grounded_in_ocr(hallucinated, ocr) is False
