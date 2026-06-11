#!/usr/bin/env python3
"""Generate PO, GRN, and commercial invoice PDFs for Purchase Management testing.

Run from repo root:
    python test-assets/generate_purchase_test_docs.py

Upload order (Purchase Management capture strip):
    1. test-po-PO-MKT-2026-TEST.pdf
    2. test-grn-PO-MKT-2026-TEST.pdf
    3. test-invoice-PO-MKT-2026-TEST.pdf
"""

from __future__ import annotations

from pathlib import Path

PO_NUMBER = "PO-MKT-2026-TEST"
VENDOR = "Sysco Foods Australia Pty Ltd"

PO_TEXT = f"""PURCHASE ORDER
{VENDOR}
ABN 51 824 753 556
Purchase Order Number: {PO_NUMBER}
PO Date: 09 June 2026
Delivery Date: 10 June 2026

Ship To: High Volt Analytics
Bill To: High Volt Analytics

Description                    Qty   Unit Price    Amount
Fresh produce delivery          10      50.00     500.00

Subtotal AUD                                   500.00
GST 10%                                          0.00
TOTAL AUD                                      500.00

Authorized by: Procurement Team
"""

GRN_TEXT = f"""GOODS RECEIPT NOTE
{VENDOR}
GRN Number: GRN-{PO_NUMBER}
PO Reference: {PO_NUMBER}
Receipt Date: 10 June 2026
Receiver: Warehouse Team

Description                    Qty Received   Condition
Fresh produce delivery                  10   Good

All items received in good condition.
Signed: J. Smith
"""

INVOICE_TEXT = f"""TAX INVOICE
{VENDOR}
ABN 51 824 753 556
Invoice Number: INV-MKT-TEST-001
PO Reference: {PO_NUMBER}
Invoice Date: 11 June 2026
Due Date: 11 July 2026

Description                    Qty   Unit Price    Amount
Fresh produce delivery          10      50.00     500.00

Subtotal AUD                                   500.00
GST 10%                                         50.00
TOTAL AUD                                      550.00

Payment terms Net 30 days.
Remit to BSB 062-000 Account 12345678
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
    docs = [
        (f"test-po-{PO_NUMBER}.pdf", PO_TEXT),
        (f"test-grn-{PO_NUMBER}.pdf", GRN_TEXT),
        (f"test-invoice-{PO_NUMBER}.pdf", INVOICE_TEXT),
    ]
    for filename, text in docs:
        path = out_dir / filename
        path.write_bytes(build_pdf(text))
        print(f"Created {path} ({path.stat().st_size} bytes)")

    print()
    print(f"Shared PO number: {PO_NUMBER}")
    print("Upload in this order (Purchase Management > Upload PO / GRN / invoice):")
    for filename, _ in docs:
        print(f"  {filename}")


if __name__ == "__main__":
    main()
