"""Pipeline enqueue dedup via Redis claims."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.workers.pipeline_enqueue import (
    filter_not_already_queued,
    release_pipeline_enqueue_claim,
    try_claim_pipeline_enqueue,
)


@pytest.fixture
def tenant_id() -> UUID:
    return UUID("550e8400-e29b-41d4-a716-446655440000")


def test_try_claim_pipeline_enqueue_without_redis(tenant_id: UUID) -> None:
    with patch("app.workers.pipeline_enqueue._redis_client", return_value=None):
        assert try_claim_pipeline_enqueue(tenant_id, 42) is True


def test_try_claim_pipeline_enqueue_sets_nx_key(tenant_id: UUID) -> None:
    client = MagicMock()
    client.set.return_value = True
    with patch("app.workers.pipeline_enqueue._redis_client", return_value=client):
        assert try_claim_pipeline_enqueue(tenant_id, 7) is True
    client.set.assert_called_once()
    key = client.set.call_args.args[0]
    assert str(tenant_id) in key
    assert "7" in key


def test_try_claim_pipeline_enqueue_skips_when_already_claimed(tenant_id: UUID) -> None:
    client = MagicMock()
    client.set.return_value = False
    with patch("app.workers.pipeline_enqueue._redis_client", return_value=client):
        assert try_claim_pipeline_enqueue(tenant_id, 7) is False


def test_filter_not_already_queued_drops_claimed_ids(tenant_id: UUID) -> None:
    client = MagicMock()
    client.mget.return_value = [None, "1", None]
    with patch("app.workers.pipeline_enqueue._redis_client", return_value=client):
        filtered = filter_not_already_queued(tenant_id, [10, 11, 12])
    assert filtered == [10, 12]


def test_release_pipeline_enqueue_claim_deletes_key(tenant_id: UUID) -> None:
    client = MagicMock()
    with patch("app.workers.pipeline_enqueue._redis_client", return_value=client):
        release_pipeline_enqueue_claim(tenant_id, 99)
    client.delete.assert_called_once()
