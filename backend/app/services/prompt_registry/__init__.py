"""Platform prompt registry package."""

from app.services.prompt_registry.catalog import PROMPT_CATALOG, get_prompt_definition
from app.services.prompt_registry.service import (
    activate_version,
    create_version,
    ensure_seeded,
    get_prompt_detail,
    invalidate_prompt_cache,
    list_prompt_summaries,
    list_versions,
    resolve_system_prompt,
    resolve_system_prompt_text,
    warm_prompt_cache,
)

__all__ = [
    "PROMPT_CATALOG",
    "activate_version",
    "create_version",
    "ensure_seeded",
    "get_prompt_definition",
    "get_prompt_detail",
    "invalidate_prompt_cache",
    "list_prompt_summaries",
    "list_versions",
    "resolve_system_prompt",
    "resolve_system_prompt_text",
    "warm_prompt_cache",
]
