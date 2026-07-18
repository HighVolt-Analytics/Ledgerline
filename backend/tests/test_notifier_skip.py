"""Invoice status notifications should not block on local SMTP defaults."""

from types import SimpleNamespace

from app.config import get_settings
from app.models.invoice import InvoiceStatus
from app.services.shared.notifier import send_notification


def test_send_notification_skips_localhost_smtp(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SMTP_HOST", "localhost")
    get_settings.cache_clear()

    invoice = SimpleNamespace(id=1, invoice_no="INV-1", vendor="Acme", total=10, currency="USD")
    called = {"smtp": False}

    def _boom(*_a, **_k):
        called["smtp"] = True
        raise AssertionError("SMTP must not be contacted for localhost")

    monkeypatch.setattr("app.services.shared.notifier.smtplib.SMTP", _boom)
    assert send_notification(invoice, InvoiceStatus.PROCESSED) is False
    assert called["smtp"] is False
    get_settings.cache_clear()
