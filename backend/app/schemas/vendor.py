"""Vendor registry schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VendorCreate(BaseModel):
    vendor_slug: str = Field(..., min_length=1, max_length=100)
    vendor_name: str = Field(..., min_length=1, max_length=255)
    sender_pattern: str = Field(..., min_length=1, max_length=255)
    abn: str | None = Field(None, min_length=11, max_length=11)
    approved: bool = False


class VendorUpdate(BaseModel):
    vendor_name: str | None = Field(None, min_length=1, max_length=255)
    sender_pattern: str | None = Field(None, min_length=1, max_length=255)
    abn: str | None = Field(None, min_length=11, max_length=11)
    approved: bool | None = None


class VendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor_slug: str
    vendor_name: str
    sender_pattern: str
    abn: str | None
    approved: bool
    created_at: datetime
