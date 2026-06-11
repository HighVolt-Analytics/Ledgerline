#!/usr/bin/env python3
"""Generate workspace-test-invoice.pdf for Inbox upload testing.

Run from repo root:
    python test-assets/generate_workspace_test_invoice.py
"""

from __future__ import annotations

from pathlib import Path

INVOICE_TEXT = """TAX INVOICE
Sysco Foods Australia Pty Ltd
ABN 51 824 753 556
Invoice Number: INV-WS-2026-001
PO Reference: PO-DEMO-2001
Invoice Date: 09 June 2026
Due Date: 09 July 2026

Description                    Qty   Unit Price    Amount
Fresh produce delivery          10      50.00     500.00
Express handling fee             1      25.00      25.00

Subtotal AUD                                   525.00
GST 10%                                         52.50
TOTAL AUD                                      577.50

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
    out = Path(__file__).resolve().parent / "workspace-test-invoice.pdf"
    out.write_bytes(build_pdf(INVOICE_TEXT))
    print(f"Created {out}")
    print(f"  Size: {out.stat().st_size} bytes")
    print("Upload via Inbox > Upload doc, or run:")
    print("  python backend/upload_workspace_test.py")


if __name__ == "__main__":
    main()
