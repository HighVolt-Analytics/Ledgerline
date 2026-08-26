"""GET /api/process/status must not wait on Celery inspect every call."""

import pytest
from httpx import AsyncClient

from app.workers import tasks as processing_tasks


@pytest.mark.asyncio
async def test_process_status_caches_celery_inspect(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    processing_tasks.reset_processing_status_cache()
    calls = {"n": 0}

    def fake_query() -> int:
        calls["n"] += 1
        return 2

    monkeypatch.setattr(processing_tasks, "_query_celery_active_count", fake_query)
    try:
        first = await client.get("/api/process/status")
        second = await client.get("/api/process/status")
    finally:
        processing_tasks.reset_processing_status_cache()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["state"] == "running"
    assert first.json()["data"]["active_tasks"] == 2
    assert second.json()["data"]["active_tasks"] == 2
    assert calls["n"] == 1
