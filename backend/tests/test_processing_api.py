"""Processing trigger runs inline when Celery is unavailable."""

import pytest
from httpx import AsyncClient

from app.config import get_settings


async def _noop_pipeline(**_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_trigger_inline_when_sync_processing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.api.processing.run_pipeline_background", _noop_pipeline)

    res = await client.post("/api/process/trigger", json={})
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "running"
    assert body["task_id"] == "inline"


@pytest.mark.asyncio
async def test_trigger_falls_back_when_celery_unavailable(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "false")
    get_settings.cache_clear()

    def _boom(*_args, **_kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.workers.tasks.process_inbox_task.delay", _boom)
    monkeypatch.setattr("app.api.processing.run_pipeline_background", _noop_pipeline)

    res = await client.post("/api/process/trigger", json={})
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "running"
