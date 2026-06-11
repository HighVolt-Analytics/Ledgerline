#!/usr/bin/env python3
"""Generate business expense PDFs for Expenses Management email testing.

Run from repo root:
    python test-assets/generate_expense_management_test_docs.py

Email test setup:
    Rule book -> Email capture (priority e.g. 40):
        attachment_name contains test-expense-
        route_to: Expenses Management
    Sender: use a vendor billing address (NOT 22je1038@...) e.g. accounts@test-vendor.com
    Mailbox: vishnu@highvolt.tech

Expense rule (example):
    vendor_contains: Telstra  -> Software Subscription Expense / Telephony
"""

from __future__ import annotations

from pathlib import Path

CLAIM_REF = "EXP-MKT-TEST"

TELSTRA_TEXT = f"""TAX INVOICE
Telstra Corporation Limited
ABN 33 051 775 556
Invoice Number: {CLAIM_REF}-TEL-001
Invoice Date: 09 June 2026
Due Date: 23 June 2026

Description                    Qty   Unit Price    Amount
Business mobile plan June 2026   1      171.82      171.82

Subtotal AUD                                    171.82
GST 10%                                          17.18
TOTAL AUD                                       189.00

Thank you for your business.
"""

UNKNOWN_SMALL_TEXT = f"""TAX INVOICE
BrightDesk Supplies Pty Ltd
ABN 91 482 331 902
Invoice Number: {CLAIM_REF}-UNK-001
Invoice Date: 09 June 2026
Due Date: 23 June 2026

Description                    Qty   Unit Price    Amount
Office stationery bundle       1      271.82      271.82

Subtotal AUD                                    271.82
GST 10%                                          27.18
TOTAL AUD                                       299.00

Thank you for your business.
"""

UNKNOWN_LARGE_TEXT = f"""TAX INVOICE
Northline IT Services Pty Ltd
ABN 88 102 445 771
Invoice Number: {CLAIM_REF}-UNK-002
Invoice Date: 09 June 2026
Due Date: 23 June 2026

Description                    Qty   Unit Price    Amount
Annual software support        1      590.91      590.91

Subtotal AUD                                    590.91
GST 10%                                          59.09
TOTAL AUD                                       650.00

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
        (
            "test-expense-telstra-EXP-MKT-TEST.pdf",
            TELSTRA_TEXT,
            "$189 — Telstra expense rule match, posts without vendor hold",
        ),
        (
            "test-expense-unknown-small-EXP-MKT-TEST.pdf",
            UNKNOWN_SMALL_TEXT,
            "$299 — unknown vendor, unmatched_expense_vendor (under $500), no hold",
        ),
        (
            "test-expense-unknown-large-EXP-MKT-TEST.pdf",
            UNKNOWN_LARGE_TEXT,
            "$650 — unknown vendor, pending_vendor hold (over $500)",
        ),
    ]
    for filename, text, note in docs:
        path = out_dir / filename
        path.write_bytes(build_pdf(text))
        print(f"Created {path} ({path.stat().st_size} bytes) — {note}")

    print()
    print("=== Email test (start with Telstra PDF) ===")
    print("1. Email capture rule: attachment_name contains test-expense-")
    print("   route_to: Expenses Management  (priority < purchase rule 100)")
    print("2. Expense rule: vendor_contains Telstra -> Telephony ledger")
    print("3. Send FROM a vendor address (not employee email), e.g.:")
    print("   billing@telstra-test.example.com")
    print("   TO: vishnu@highvolt.tech")
    print("   ATTACH: test-expense-telstra-EXP-MKT-TEST.pdf")
    print("4. Expected: /expenses page, Travel/Software GL, processed or needs_review")


if __name__ == "__main__":
    main()
