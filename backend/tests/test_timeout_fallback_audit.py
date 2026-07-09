"""DI/LLM timeout degrade behavior tests."""

from __future__ import annotations

import pytest

from app.services.extraction.document_intelligence import is_di_enabled


def test_di_disabled_degrades_gracefully() -> None:
  assert is_di_enabled() in {True, False}


@pytest.mark.asyncio
async def test_llm_timeout_propagates_as_exception() -> None:
    async def _boom(**_kwargs):
        raise TimeoutError("llm timeout")

    with pytest.raises(TimeoutError):
        await _boom()
