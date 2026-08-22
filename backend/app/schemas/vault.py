from datetime import date
from decimal import Decimal
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
    document_ref: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    total: Decimal | None = None
    currency: str = ""
    capture_source: str | None = None
    document_heading: str | None = None
    document_type_code: str | None = None


class VaultTreeResponse(BaseModel):
    tree: list[VaultTreeNode]
    files: list[VaultFileEntry]
    blob_enabled: bool
    file_count: int = 0


class VaultFilesResponse(BaseModel):
    files: list[VaultFileEntry]
    count: int = 0


class VaultDocumentSetInvoice(BaseModel):
    id: int
    vendor: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    document_ref: str | None = None
    total: Decimal | None = None
    currency: str = ""
    capture_source: str | None = None
    document_heading: str | None = None
    document_type_code: str | None = None
    purchase_document_type: str | None = None


class VaultDocumentSetCard(BaseModel):
    id: str
    pattern: str
    set_name: str
    isolated: bool = False
    match_count: int = 0
    invoices: list[VaultDocumentSetInvoice] = Field(default_factory=list)


class VaultDocumentSetsResponse(BaseModel):
    sets: list[VaultDocumentSetCard] = Field(default_factory=list)


class VaultMigrateResponse(BaseModel):
    moved: int
    skipped: int
    blob_enabled: bool
