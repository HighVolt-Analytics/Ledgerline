from pydantic import BaseModel, Field

from app.tenant_settings import COUNTRY_CURRENCY, DEFAULT_COUNTRY

_DEFAULT_CURRENCY = COUNTRY_CURRENCY[DEFAULT_COUNTRY]


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    currency: str = Field(default=_DEFAULT_CURRENCY, min_length=3, max_length=3)


class TenantResponse(BaseModel):
    id: int
    name: str
    slug: str
    currency: str = _DEFAULT_CURRENCY
    is_current: bool = True
