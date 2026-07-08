"""Pipeline guards for counterparty registration holds."""

from app.models.invoice import Invoice
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_VENDOR
from app.services.invoice.pipeline import _counterparty_registration_pending


def test_counterparty_registration_pending_when_pending_vendor() -> None:
    inv = Invoice(evaluation_status=EVAL_PENDING_VENDOR, currency="AUD", file_hash="x")
    assert _counterparty_registration_pending(inv) is True


def test_counterparty_registration_pending_when_needs_review() -> None:
    inv = Invoice(evaluation_status="needs_review", currency="AUD", file_hash="x")
    assert _counterparty_registration_pending(inv) is False
