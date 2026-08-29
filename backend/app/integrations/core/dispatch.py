"""Send one canonical document to one or more adapters. v1: Xero only (not wired yet)."""

from __future__ import annotations

from typing import Any

SUPPORTED_ADAPTERS = ("xero",)


async def send(canonical: dict[str, Any], adapters: list[str]) -> None:
    if not adapters:
        raise ValueError("at least one adapter is required")
    unknown = [name for name in adapters if name not in SUPPORTED_ADAPTERS]
    if unknown:
        raise ValueError(f"unsupported adapters: {unknown}")
    raise NotImplementedError("adapter send is not part of Stage 1")
