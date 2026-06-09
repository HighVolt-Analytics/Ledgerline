# Phase B — Masters, holds, and team policy

Implements architecture §6–§8 hold/enforcement behaviour.

## B.1 Pending vendor hold

When `evaluation_status` is `pending_vendor` or the vendor name is in the pending registration queue:

- Pipeline stops before validation / mapping (`vendor_registration_hold` audit event)
- Invoice status → `exception` until the vendor is promoted

**Release:** `POST /api/pending-vendors/{id}/promote` re-evaluates linked invoices and resets them to `pending` for reprocessing.

Module: `vendor_hold_service.py`

## B.2 Employee master enforcement

Team expense validation (`VR-TE01` … `VR-TE06`) at VALIDATE:

| Rule | Check |
|------|--------|
| VR-TE01 | Identity via email, WhatsApp, or Viber |
| VR-TE02 | Monthly, quarterly, and annual budget caps |
| VR-TE03 | Receipt policy from matched team rule |
| VR-TE04 | Bank account on file |
| VR-TE05 | Employee status Active (blocks Suspended / Pending verification) |
| VR-TE06 | Per-category ledger cap |

Channel rules on team expense rules use `capture_channel` inferred from sender (`email` vs `mob`).

## B.3 Team policy at approval

- **Auto-approve below:** claims under `auto_approve_below` bypass receipt-only validation failures in the pipeline
- **Approval gate:** `POST /api/approvals/{id}/approve` re-checks receipt policy for team expenses before reprocess

Modules: `team_expense_approval.py`, `team_expense_validator.py`

## Verify

```powershell
cd backend
pytest tests/test_phase_b_masters.py tests/test_phase6_ingest.py -q
```
