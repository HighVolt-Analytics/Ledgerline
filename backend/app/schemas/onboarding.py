"""Tenant onboarding status schemas."""

from pydantic import BaseModel, Field


class OnboardingStatusResponse(BaseModel):
    completed: bool
    country: str
    industry: str | None = None
    steps: list[str] = Field(default_factory=list)


class UpdateOnboardingRequest(BaseModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    industry: str | None = Field(default=None, max_length=100)
    complete: bool = False
