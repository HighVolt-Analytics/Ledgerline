# Journal vs invoice-row amounts (known gap)

Status: **open** — not in the understood-path extraction five-commit set.

## Symptom

Aged Payables, Payment Schedule, and Cash Forecast read outstanding from journal lines (`sum(credit − debit)`). Invoice Register, Vendor Spend Summary, and the document registry read `invoice.total` (and related header columns).

If `generate_entries` runs on a row whose stored `subtotal` / `gst` / `total` do not reconcile, [`resolve_invoice_amounts`](../app/services/invoice/invoice_amounts.py) **rewrites the computed subtotal** (typically `total − gst`, or the non-tax line sum) for journal lines only. The invoice row is not updated. The journal posts “successfully.” Ledger-true reports and invoice-row reports then disagree on the same document with no exception status.

That is the same failure shape as the original partial-payment AP split (reports disagreeing because they read different sources), entering through journal identity instead of settlement.

## How a mismatch reaches journal

- Understood path: `vision_should_continue_posting` (amount gate, this round) plus later VR01, unless validation is bypassed.
- Not-understood / OCR path: VR01 (`Total != subtotal + GST`) holds before journal, unless validation is skipped.
- Remaining door: human-approval / Confirm bypass, or Confirm with unreconciled numbers still on the row → `generate_entries` still silently balances lines.

[`backfill_invoice_amounts_from_sources`](../app/services/invoice/invoice_amounts.py) only fills **missing** header amounts; it does not overwrite a present mismatch.

## Closing it (later)

Make `resolve_invoice_amounts` / `generate_entries` **refuse** (halt journaling) when all three amounts are present and inconsistent, instead of manufacturing a balancing subtotal. That is a cross-path finance change, not a vision-extract patch.

Do not “fix” this by pointing Invoice Register at the journal without an explicit product decision — the row is still the source of truth for unpaid / unposted documents.
