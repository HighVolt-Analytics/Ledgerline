#!/usr/bin/env python3
"""Generate team expense receipt PDFs for email / Team Expenses testing.

Run from repo root:
    python test-assets/generate_team_expense_test_docs.py

Email test (recommended rule book setup — see script output):
    Send from: 22je1038@iitism.ac.in  (or your configured employee email)
    Attach:   test-team-meal-TE-MKT-TEST.pdf

Designed to match a team rule like:
    description_contains: meal / lunch
    auto_approve_below: 30
    receipt_threshold: 25
"""

from __future__ import annotations

from pathlib import Path

CLAIM_REF = "TE-MKT-TEST"
MERCHANT = "Riverside Cafe Pty Ltd"
MERCHANT_ABN = "83 147 562 901"

SMALL_MEAL_TEXT = f"""TAX INVOICE
{MERCHANT}
ABN {MERCHANT_ABN}
Invoice Number: {CLAIM_REF}-001
Invoice Date: 09 June 2026

Description                    Qty   Unit Price    Amount
Site supervisor team lunch meal   1      22.27      22.27

Subtotal AUD                                    22.27
GST 10%                                          2.23
TOTAL AUD                                       24.50

Thank you for your visit.
"""

LARGE_MEAL_TEXT = f"""TAX INVOICE
{MERCHANT}
ABN {MERCHANT_ABN}
Invoice Number: {CLAIM_REF}-002
Invoice Date: 09 June 2026

Description                    Qty   Unit Price    Amount
Site supervisor team lunch meal   1      50.00      50.00

Subtotal AUD                                    50.00
GST 10%                                          5.00
TOTAL AUD                                       55.00

Thank you for your visit.
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
            f"test-team-meal-{CLAIM_REF}.pdf",
            SMALL_MEAL_TEXT,
            "$24.50 — auto-approve path (below $30 threshold)",
        ),
        (
            f"test-team-meal-large-{CLAIM_REF}.pdf",
            LARGE_MEAL_TEXT,
            "$55.00 — manager approval path (at/above $30 threshold)",
        ),
    ]
    for filename, text, note in docs:
        path = out_dir / filename
        path.write_bytes(build_pdf(text))
        print(f"Created {path} ({path.stat().st_size} bytes) — {note}")

    print()
    print("=== Email test checklist ===")
    print("1. Rule book -> Employees: add employee with email = your sender")
    print("   (e.g. 22je1038@iitism.ac.in), bank account, status Active, budget caps")
    print("2. Rule book -> Team expense rules: enable e.g. 'Site supervisor meals'")
    print("   match: description meal/lunch - ledger Travel Expense")
    print("   policy: receipt_threshold 25 - auto_approve_below 30")
    print("3. Rule book -> Email capture: NEW rule (priority < 100), e.g. priority 50")
    print("   AND: from contains your sender")
    print("   AND: attachment_name contains test-team-")
    print("   -> route to Team Expenses")
    print("   (Keep existing Sysco purchase rule for test-po- / test-grn- / test-invoice-)")
    print()
    print("4. Email the small PDF first:")
    print(f"   Attachment: test-team-meal-{CLAIM_REF}.pdf")
    print("   Expected: Team Expenses → VR-TE pass → auto-post if under $30")
    print()
    print("5. Optional second email: test-team-meal-large-*.pdf → Approvals queue")


if __name__ == "__main__":
    main()
