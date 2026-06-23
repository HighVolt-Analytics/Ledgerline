"""Well-known tenant UUIDs (stable across environments after migration 029)."""

import uuid

TESTING_TENANT_UUID = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")
PLATFORM_TENANT_UUID = uuid.UUID("550e8400-e29b-41d4-a716-446655440002")


def parse_tenant_id(value: str | uuid.UUID | int | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, int):
        legacy = {1: TESTING_TENANT_UUID, 2: PLATFORM_TENANT_UUID}.get(value)
        if legacy is not None:
            return legacy
    if isinstance(value, uuid.UUID):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError:
        return None
