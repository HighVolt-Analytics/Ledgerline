from enum import Enum

from pydantic import BaseModel, Field


class VaultNodeKind(str, Enum):
    ORG = "org"
    VENDOR = "vendor"
    YEAR = "year"
    MONTH = "month"


class VaultTreeNode(BaseModel):
    id: str
    label: str
    kind: VaultNodeKind
    count: int
    children: list["VaultTreeNode"] = Field(default_factory=list)


class VaultFileEntry(BaseModel):
    invoice_id: int
    org: str
    vendor: str
    year: str
    month: str
    file_name: str
    virtual_path: str
    blob_path: str | None = None
    has_stored_file: bool = False


class VaultTreeResponse(BaseModel):
    tree: list[VaultTreeNode]
    files: list[VaultFileEntry]
    blob_enabled: bool


class VaultMigrateResponse(BaseModel):
    moved: int
    skipped: int
    blob_enabled: bool
