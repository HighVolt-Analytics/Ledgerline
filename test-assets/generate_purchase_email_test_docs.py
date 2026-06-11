#!/usr/bin/env python3
"""Generate fresh PO / GRN / invoice PDFs for Purchase Management email testing.

Run from repo root:
    python test-assets/generate_purchase_email_test_docs.py

Optional custom PO number:
    python test-assets/generate_purchase_email_test_docs.py PO-MKT-2026-JUN9
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# New batch — avoids collision with PO-MKT-2026-TEST already in the database.
DEFAULT_PO_NUMBER = "PO-MKT-2026-JUN9"
VENDOR = "Sysco Foods Australia Pty Ltd"
VENDOR_ABN = "51 824 753 556"
INVOICE_NO = "INV-MKT-JUN9-001"
GRN_NO = "GRN-PO-MKT-2026-JUN9"


def _texts(po_number: str) -> tuple[str, str, str]:
    po_text = f"""PURCHASE ORDER
{VENDOR}
ABN {VENDOR_ABN}
Purchase Order Number: {po_number}
PO Date: 09 June 2026
Delivery Date: 11 June 2026

Ship To: High Volt Analytics
Bill To: High Volt Analytics

Description                    Qty   Unit Price    Amount
Fresh produce delivery          10      50.00     500.00

Subtotal AUD                                   500.00
GST 10%                                          0.00
TOTAL AUD                                      500.00

Authorized by: Procurement Team
"""

    grn_text = f"""GOODS RECEIPT NOTE
{VENDOR}
GRN Number: {GRN_NO}
PO Reference: {po_number}
Receipt Date: 11 June 2026
Receiver: Warehouse Team

Description                    Qty Received   Condition
Fresh produce delivery                  10   Good

All items received in good condition.
Signed: J. Smith
"""

    invoice_text = f"""TAX INVOICE
{VENDOR}
ABN {VENDOR_ABN}
Invoice Number: {INVOICE_NO}
PO Reference: {po_number}
Invoice Date: 12 June 2026
Due Date: 12 July 2026

Description                    Qty   Unit Price    Amount
Fresh produce delivery          10      50.00     500.00

Subtotal AUD                                   500.00
GST 10%                                         50.00
TOTAL AUD                                      550.00

Payment terms Net 30 days.
Remit to BSB 033-099 Account 98765432
Thank you for your business.
"""
    return po_text, grn_text, invoice_text


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
    po_number = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PO_NUMBER
    po_text, grn_text, invoice_text = _texts(po_number)

    out_dir = Path(__file__).resolve().parent
    docs = [
        (f"purchase-test-po-{po_number}.pdf", po_text),
        (f"purchase-test-grn-{po_number}.pdf", grn_text),
        (f"purchase-test-invoice-{po_number}.pdf", invoice_text),
    ]

    created: list[Path] = []
    for filename, text in docs:
        path = out_dir / filename
        path.write_bytes(build_pdf(text))
        created.append(path)
        print(f"Created {path} ({path.stat().st_size} bytes)")

    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        for path in created:
            dest = downloads / path.name
            shutil.copy2(path, dest)
            print(f"Copied  {dest}")

    print()
    print("=" * 72)
    print("PURCHASE MANAGEMENT EMAIL TEST")
    print("=" * 72)
    print(f"Shared PO number : {po_number}")
    print(f"Vendor           : {VENDOR}")
    print(f"Invoice number   : {INVOICE_NO}")
    print()
    print("Rule book — add ONE email capture rule (if not already present):")
    print("  Name     : Purchase test documents (email)")
    print("  Priority : 5 (before generic rules)")
    print("  Mailbox  : vishnu@highvolt.tech  (your connected mailbox)")
    print("  AND:")
    print("    from contains            22je1038@iitism.ac.in  (your sender)")
    print("    attachment_name contains purchase-test-")
    print("  Route to : Purchase Management")
    print()
    print("Matches purchase rule pr-3: po_regex PO-MKT-2026 -> Marketing Expense")
    print()
    print("Send THREE separate emails (wait ~30s between each for processing):")
    print()
    for index, (filename, _) in enumerate(docs, start=1):
        print(f"  {index}. Subject: purchase {filename.split('-')[2]} {po_number}")
        print(f"     Attach:  {filename}")
    print()
    print("Expected in LedgerLink:")
    print("  Email 1 → Purchase Management, document type PO, PO register created")
    print("  Email 2 → GRN linked to same PO, qty 10 received")
    print("  Email 3 → Commercial invoice, three-way match = Matched")
    print()
    print("Ensure Celery worker + beat are running for email ingest.")
    print("=" * 72)


if __name__ == "__main__":
    main()
