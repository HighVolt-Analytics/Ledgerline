"""Document id formatting for live rule-book evaluation."""

from app.models.invoice import Invoice
from app.services.rule_book_evaluate_service import invoice_to_eval_document


def test_invoice_to_eval_document_uses_canonical_doc_number() -> None:
    inv = Invoice(org_id=1, currency="AUD", invoice_no="INV-GS-0101", document_ref="DOC-2")
    inv.id = 94

    doc = invoice_to_eval_document(inv)

    assert doc.doc_number == "DOC-2"
    assert doc.invoice_no == "INV-GS-0101"
