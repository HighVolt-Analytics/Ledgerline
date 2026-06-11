"""Classification rule book config API."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.services.account_mapper import clear_rule_book_cache


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
