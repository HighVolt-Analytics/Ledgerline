"""Tenant locale date order tests."""

from app.tenant_settings import tenant_date_order


class _Tenant:
    def __init__(self, settings_json: dict | None) -> None:
        self.settings_json = settings_json


def test_tenant_date_order_defaults_to_dmy_for_singapore() -> None:
    tenant = _Tenant({"country": "SG"})
    assert tenant_date_order(tenant) == "DMY"


def test_tenant_date_order_uses_mdy_for_us() -> None:
    tenant = _Tenant({"country": "US"})
    assert tenant_date_order(tenant) == "MDY"
