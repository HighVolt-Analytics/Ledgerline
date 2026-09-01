#!/usr/bin/env python3
"""Generate PO / GRN / Invoice PDFs to manually verify the 3 P0 AP fixes:

  1. VR13 bank-details fraud control (match / mismatch-block / no-master-data-skip)
  2. Payment segregation of duties (needs 2 approver users - not a document, see checklist)
  3. RC1 reconciliation with vendor sub-ledger codes (needs COA config - not a document)

This script only produces the source documents for #1's three branches, feeding
realistic invoices through ingest -> OCR -> 3-way match -> validation so VR13
actually gets exercised end to end (not just unit-tested).

Run from repo root or from test-assets/:
    python test-assets/generate_p0_verification_docs.py

Before uploading, create these TWO vendors in Vendor Master (exact spelling/ABN
matters for VR12/VR13 matching):

  Vendor A - "Ridgeline Test Supplies Pty Ltd"
    ABN: 51 824 753 556
    Bank: BSB 062-777, Account 55667788

  Vendor B - "Northgate Test Traders Pty Ltd"
    ABN: 60 417 253 884
    Bank: leave BLANK (do not enter bank details for this vendor)

Upload order per scenario (Purchase Management > Upload PO / GRN / invoice):
  Scenario 1 - clean match (VR13 should PASS):
    p0test-po-A-CLEAN.pdf, p0test-grn-A-CLEAN.pdf, p0test-invoice-A-CLEAN.pdf
  Scenario 2 - bank mismatch (VR13 should BLOCK, unbypassable):
    p0test-po-A-FRAUD.pdf, p0test-grn-A-FRAUD.pdf, p0test-invoice-A-FRAUD.pdf
  Scenario 3 - vendor has no bank on file (VR13 should SKIP, not block):
    p0test-po-B-NOBANK.pdf, p0test-grn-B-NOBANK.pdf, p0test-invoice-B-NOBANK.pdf
"""

from __future__ import annotations

import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Vendor A - Ridgeline Test Supplies (used for clean-match and fraud scenarios)
# ---------------------------------------------------------------------------
VENDOR_A = "Ridgeline Test Supplies Pty Ltd"
VENDOR_A_ABN = "51824753556"
MASTER_BANK_BSB = "062-777"
MASTER_BANK_ACCOUNT = "55667788"
FRAUD_BANK_BSB = "999-000"
FRAUD_BANK_ACCOUNT = "90009000"

# ---------------------------------------------------------------------------
# Vendor B - Northgate Test Traders (no bank details entered in master)
# ---------------------------------------------------------------------------
VENDOR_B = "Northgate Test Traders Pty Ltd"
VENDOR_B_ABN = "60417253884"
VENDOR_B_INVOICE_BANK_BSB = "084-004"
VENDOR_B_INVOICE_BANK_ACCOUNT = "11220033"


def _abn_spaced(abn: str) -> str:
    return f"{abn[:2]} {abn[2:5]} {abn[5:8]} {abn[8:]}"


def po_text(*, po_number: str, vendor: str, abn: str, qty: int, unit_price: float) -> str:
    amount = qty * unit_price
    return f"""PURCHASE ORDER
{vendor}
ABN {_abn_spaced(abn)}
Purchase Order Number: {po_number}
PO Date: 01 September 2026
Delivery Date: 03 September 2026

Ship To: High Volt Analytics
Bill To: High Volt Analytics

Description                    Qty   Unit Price    Amount
Test verification stock         {qty}      {unit_price:.2f}     {amount:.2f}

Subtotal AUD                                   {amount:.2f}
GST 10%                                          {amount * 0.1:.2f}
TOTAL AUD                                      {amount * 1.1:.2f}

Authorized by: Procurement Team
"""


def grn_text(*, po_number: str, vendor: str, qty: int) -> str:
    return f"""GOODS RECEIPT NOTE
{vendor}
GRN Number: GRN-{po_number}
PO Reference: {po_number}
Receipt Date: 03 September 2026
Receiver: Warehouse Team

Description                    Qty Received   Condition
Test verification stock                 {qty}   Good

All items received in good condition.
Signed: J. Smith
"""


def invoice_text(
    *,
    invoice_number: str,
    po_number: str,
    vendor: str,
    abn: str,
    qty: int,
    unit_price: float,
    bank_bsb: str,
    bank_account: str,
) -> str:
    amount = qty * unit_price
    gst = amount * 0.1
    total = amount + gst
    return f"""TAX INVOICE
{vendor}
ABN {_abn_spaced(abn)}
Invoice Number: {invoice_number}
PO Reference: {po_number}
Invoice Date: 04 September 2026
Due Date: 04 October 2026

Description                    Qty   Unit Price    Amount
Test verification stock         {qty}      {unit_price:.2f}     {amount:.2f}

Subtotal AUD                                   {amount:.2f}
GST 10%                                         {gst:.2f}
TOTAL AUD                                      {total:.2f}

Payment terms Net 30 days.
Remit to BSB {bank_bsb} Account {bank_account}
Thank you for your business.
"""


def _escape_pdf(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(text: str) -> bytes:
    lines = text.strip().split("\n")
    content = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for index, line in enumerate(lines):
        if index == 0:
            content.append(f"({_escape_pdf(line)}) Tj")
        else:
            content.append("T*")
            content.append(f"({_escape_pdf(line)}) Tj")
    content.append("ET")
    stream = "\n".join(content)
    stream_bytes = stream.encode("latin-1", errors="replace")

    objects: list[tuple[int, str]] = [
        (1, "<< /Type /Catalog /Pages 2 0 R >>"),
        (2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            3,
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        (4, f"<< /Length {len(stream_bytes)} >>\nstream\n{stream}\nendstream"),
        (5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]

    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for number, body in objects:
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")

    xref_start = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode()
    return pdf


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    qty, unit_price = 8, 65.00

    scenarios = [
        # (tag, po_number, invoice_number, vendor, abn, bank_bsb, bank_account)
        (
            "A-CLEAN",
            "PO-P0-A-CLEAN",
            "INV-P0-A-CLEAN-001",
            VENDOR_A,
            VENDOR_A_ABN,
            MASTER_BANK_BSB,
            MASTER_BANK_ACCOUNT,
        ),
        (
            "A-FRAUD",
            "PO-P0-A-FRAUD",
            "INV-P0-A-FRAUD-001",
            VENDOR_A,
            VENDOR_A_ABN,
            FRAUD_BANK_BSB,
            FRAUD_BANK_ACCOUNT,
        ),
        (
            "B-NOBANK",
            "PO-P0-B-NOBANK",
            "INV-P0-B-NOBANK-001",
            VENDOR_B,
            VENDOR_B_ABN,
            VENDOR_B_INVOICE_BANK_BSB,
            VENDOR_B_INVOICE_BANK_ACCOUNT,
        ),
    ]

    created: list[Path] = []
    for tag, po_number, invoice_number, vendor, abn, bank_bsb, bank_account in scenarios:
        docs = [
            (f"p0test-po-{tag}.pdf", po_text(po_number=po_number, vendor=vendor, abn=abn, qty=qty, unit_price=unit_price)),
            (f"p0test-grn-{tag}.pdf", grn_text(po_number=po_number, vendor=vendor, qty=qty)),
            (
                f"p0test-invoice-{tag}.pdf",
                invoice_text(
                    invoice_number=invoice_number,
                    po_number=po_number,
                    vendor=vendor,
                    abn=abn,
                    qty=qty,
                    unit_price=unit_price,
                    bank_bsb=bank_bsb,
                    bank_account=bank_account,
                ),
            ),
        ]
        for filename, text in docs:
            path = out_dir / filename
            path.write_bytes(build_pdf(text))
            created.append(path)
            print(f"Created {path.name} ({path.stat().st_size} bytes)")

    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        for path in created:
            try:
                shutil.copy2(path, downloads / path.name)
            except OSError:
                pass

    print()
    print("Vendor A (Ridgeline Test Supplies, ABN 51 824 753 556):")
    print(f"  master bank on file -> BSB {MASTER_BANK_BSB} / Account {MASTER_BANK_ACCOUNT}")
    print("Vendor B (Northgate Test Traders, ABN 60 417 253 884):")
    print("  master bank on file -> leave blank")


if __name__ == "__main__":
    main()
