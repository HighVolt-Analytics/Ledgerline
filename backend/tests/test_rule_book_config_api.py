
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Classification rule book config API."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.rule_book.account_mapper import clear_rule_book_cache


@pytest.mark.asyncio
async def test_rule_book_config_get_put_roundtrip(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = Path(get_settings().rule_book_config_path)
    if not template.is_file():
        template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_rule_book_cache()

    assert template.is_file(), "rule_book_config.json template missing"

    res = await client.get("/api/rule-book/config")
    assert res.status_code == 200
    original = res.json()["data"]
    assert original["schema_version"] == 1
    assert len(original["email_capture_rules"]) >= 1

    updated = {
        **original,
        "vendor_detection_config": {
            **original["vendor_detection_config"],
            "threshold": 75,
        },
    }
    res = await client.put("/api/rule-book/config", json=updated)
    assert res.status_code == 200
    assert res.json()["data"]["vendor_detection_config"]["threshold"] == 75

    res = await client.get("/api/rule-book/config")
    assert res.json()["data"]["vendor_detection_config"]["threshold"] == 75

    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_saved_org_config_not_overwritten_when_template_newer(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Org PUT must persist; later template edits must not replace saved rules on GET."""
    import time

    source_template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    template = tmp_path / "template_rule_book.json"
    template.write_text(source_template.read_text(encoding="utf-8"), encoding="utf-8")
    upload = tmp_path / "uploads"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    get_settings.cache_clear()
    clear_rule_book_cache()

    res = await client.get("/api/rule-book/config")
    original = res.json()["data"]
    custom = {
        **original,
        "email_capture_rules": [
            {
                **original["email_capture_rules"][0],
                "id": "ec-custom-only",
                "name": "My saved capture rule",
            }
        ],
    }
    res = await client.put("/api/rule-book/config", json=custom)
    assert res.status_code == 200

    time.sleep(0.05)
    template.write_text(
        json.dumps({**original, "email_capture_rules": []}, indent=2) + "\n",
        encoding="utf-8",
    )

    get_settings.cache_clear()
    clear_rule_book_cache()
    res = await client.get("/api/rule-book/config")
    rules = res.json()["data"]["email_capture_rules"]
    assert len(rules) == 1
    assert rules[0]["id"] == "ec-custom-only"

    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_rule_book_config_validates_nested_conditions(client: AsyncClient) -> None:
    res = await client.get("/api/rule-book/config")
    body = res.json()["data"]
    body["email_capture_rules"] = [
        {
            "id": "bad",
            "name": "Bad rule",
            "enabled": True,
            "priority": 1,
            "mailbox": "test@example.com",
            "root": {"type": "group", "operator": "AND", "children": []},
            "action": {"save_attachment": True, "route_to": "Vault", "tags": []},
            "matched_count": 0,
            "last_matched": "",
        }
    ]
    res = await client.put("/api/rule-book/config", json=body)
    assert res.status_code == 200

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_delete_document_type_persists(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE removes a catalogue row immediately even when a PUT is still buffered."""
    from app.services.rule_book.rule_book_save_buffer import clear_rule_book_save_buffers, flush_rule_book_save_buffer

    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    catalog = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "document_types_test_catalog.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RULE_BOOK_SAVE_DEBOUNCE_MS", "200")
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_rule_book_save_buffers()

    body = (await client.get("/api/rule-book/config")).json()["data"]
    types = json.loads(catalog.read_text(encoding="utf-8"))
    custom = next(row for row in types if row["code"] == "DT-01")
    extra = {**custom, "code": "DT-99", "title": "Disposable test type", "shortTitle": "Disposable"}
    body["document_types"] = [*body.get("document_types", []), extra]

    await client.put("/api/rule-book/config", json=body)
    codes = {row["code"] for row in (await client.get("/api/rule-book/config")).json()["data"]["document_types"]}
    assert "DT-99" in codes

    res = await client.delete("/api/rule-book/document-types/DT-99")
    assert res.status_code == 200
    codes = {row["code"] for row in res.json()["data"]["document_types"]}
    assert "DT-99" not in codes

    res = await client.get("/api/rule-book/config")
    codes = {row["code"] for row in res.json()["data"]["document_types"]}
    assert "DT-99" not in codes

    await flush_rule_book_save_buffer(TESTING_TENANT_UUID, db=db_session)
    await db_session.commit()

    res = await client.get("/api/rule-book/config")
    codes = {row["code"] for row in res.json()["data"]["document_types"]}
    assert "DT-99" not in codes

    clear_rule_book_save_buffers()
    get_settings.cache_clear()
    clear_rule_book_cache()


def test_document_type_required_fields_roundtrip() -> None:
    """Partial and empty required_fields survive validate/save normalization."""
    from app.schemas.rule_book_config import (
        validate_rule_book_config_for_save,
        validate_rule_book_config_payload,
    )

    minimal_classifier = {
        "enabled": False,
        "priority": 100,
        "confidence": 0.85,
        "root": {"type": "group", "operator": "AND", "children": []},
    }
    partial = {
        "code": "DT-98",
        "title": "Compulsory subset test",
        "short_title": "Compulsory subset",
        "klass": "Non-trans, non-posting",
        "posting": "No",
        "route_target": "Vault",
        "enabled": False,
        "recognition_mode": "signals",
        "recognition_signals": [],
        "llm_prompt": "",
        "classifier": minimal_classifier,
        "extraction_fields": ["vendor", "total", "invoice_no"],
        "required_fields": ["vendor"],
        "post_to": {"ledger": "", "sub_ledger": ""},
    }
    empty_required = {
        **partial,
        "code": "DT-97",
        "title": "No compulsory test",
        "short_title": "No compulsory",
        "extraction_fields": ["vendor", "total"],
        "required_fields": [],
    }
    body = {"schema_version": 1, "document_types": [partial, empty_required]}

    saved = validate_rule_book_config_for_save(body)
    by_code = {row.code: row for row in saved.document_types}
    assert by_code["DT-98"].required_fields == ["vendor"]
    assert by_code["DT-98"].extraction_fields == ["vendor", "total", "invoice_no"]
    assert by_code["DT-97"].required_fields == []
    assert by_code["DT-97"].extraction_fields == ["vendor", "total"]

    reloaded = validate_rule_book_config_payload(saved.model_dump())
    by_code = {row.code: row for row in reloaded.document_types}
    assert by_code["DT-98"].required_fields == ["vendor"]
    assert by_code["DT-97"].required_fields == []
