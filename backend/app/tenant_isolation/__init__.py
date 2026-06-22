"""Tenant-prefixed Redis cache keys."""


def tenant_cache_key(tenant_id: int, logical_key: str) -> str:
    return f"tenant:{tenant_id}:v1:{logical_key}"


def tenant_slug_cache_key(slug: str) -> str:
    return f"cache:tenant_slug:{slug.lower()}"
