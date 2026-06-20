from enum import Enum

from pydantic import BaseModel, Field


class VaultNodeKind(str, Enum):
    ORG = "org"
    BOOK = "book"
    DOCUMENT_TYPE = "document_type"
    VENDOR = "vendor"
    YEAR = "year"
    MONTH = "month"
    PO = "po"


class VaultTreeNode(BaseModel):
    id: str
    label: str
    kind: VaultNodeKind
    count: int
    children: list["VaultTreeNode"] = Field(default_factory=list)


class VaultFileEntry(BaseModel):
    invoice_id: int
    org: str
    book: str
    document_type: str | None = None
    vendor: str
    year: str
    month: str
    po_folder: str | None = None
    purchase_document_type: str | None = None
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
