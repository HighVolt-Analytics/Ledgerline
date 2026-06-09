from pydantic import BaseModel, Field


class CreateOrganisationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    currency: str = Field(default="AUD", min_length=3, max_length=3)


class OrganisationResponse(BaseModel):
    id: int
    name: str
    slug: str
    currency: str = "AUD"
    is_current: bool = True
