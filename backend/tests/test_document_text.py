from app.services.extraction.document_text import cap_document_text, sanitize_postgres_text


def test_sanitize_postgres_text_strips_nul_bytes() -> None:
    assert sanitize_postgres_text("CK5QT5BF\x000015") == "CK5QT5BF0015"
    assert sanitize_postgres_text(None) == ""


def test_cap_document_text_strips_nul_bytes() -> None:
    text = "Invoice number CK5QT5BF\x000015\nTotal $20.00"
    assert "\x00" not in cap_document_text(text)
    assert "CK5QT5BF0015" in cap_document_text(text)
