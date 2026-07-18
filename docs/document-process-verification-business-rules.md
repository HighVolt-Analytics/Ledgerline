# Document Process Verification — Business Rules (Testing)

**Purpose:** Testable business rules for the document ingest → classify → extract → validate → match → approve → post pipeline, derived from the current codebase.

**Audience:** QA, SDET, and developers writing regression / E2E cases.

**Source of truth:** Code under `backend/app/services/` (not UI copy). Thresholds below are **defaults**; tenants may override via Rule Book / env.

**Last aligned to codebase:** 2026-07-15

---

## How to use this document

For each rule ID:

| Column | Meaning |
|--------|---------|
| **Pass** | Expected happy path |
| **Fail** | Blocking failure → `status=exception` (unless noted) |
| **Warn / skip** | Does **not** block `all_passed` |
| **Override** | Tenant / env / reprocess skip that changes behaviour |

**Pipeline pass semantics (`all_passed`):** a validation set passes when every result is `passed`, `skipped`, **or** failed with `severity=warn`.

```text
all_passed = ∀ r: r.passed ∨ r.skipped ∨ (¬r.passed ∧ r.severity = "warn")
```

Source: `backend/app/services/rule_book/validator.py` → `all_passed`

---

## 1. Document lifecycle

### 1.1 Pipeline status (`InvoiceStatus`)

| Status | When set | Test expectation |
|--------|----------|------------------|
| `pending` | Queued / received | Appears before OCR starts |
| `parsing` | OCR / extract in progress | Transient |
| `validating` | Validation rules running | Transient |
| `mapping` | GL / rule-book mapping | Transient |
| `journaling` | Journal generation | Transient |
| `reconciling` | Reconciliation | Transient |
| `processed` | Clean path finished | Ready for post / posted path |
| `exception` | Any blocking gate / hold | Human review queue |
| `duplicate_skipped` | Duplicate file hash / ingest skip | Not reprocessed as new |
| `rejected` | Human/system reject | Terminal unless reprocess |

Source: `backend/app/schemas/invoice.py` → `InvoiceStatus`

### 1.2 Evaluation status (`EvaluationStatus`)

| Eval status | Typical gate / trigger |
|-------------|------------------------|
| `auto_coded` | Routing/coding succeeded without hold |
| `needs_review` | Low field confidence, fallback mapping, playbook/field issues, unknown legacy values |
| `pending_approval` | DT approval gate / team expense approval |
| `awaiting_classification` | Classification confidence / recognition gate failed |
| `needs_rescan` | Image quality / sparse OCR gate failed |
| `pending_vendor` | Unknown vendor/customer below match threshold (hold) |
| `unmatched_expense_vendor` | Expenses route: unknown vendor but amount ≤ hold-above |
| `awaiting_po` | Purchase doc waiting for PO |
| `awaiting_so` | Sales doc waiting for SO |

Unknown legacy DB values → map to `needs_review` via `parse_evaluation_status`.

Source: `backend/app/schemas/invoice.py`, `invoice_evaluation_service.py`

### 1.3 Narrative UI stages

Matrix narrative: **Received → Parsed → Validated → Mapped → Approved → Posted**

Early audit stages (when present): **Storage → File validity → Vision understand → Vision header → Image quality → Layout readiness → OCR → OCR quality → Classified → Gate**

Source: `backend/app/services/invoice/pipeline_stages.py`

### 1.4 Approval board & UI action eligibility

Board columns: `review | processing | approved | rejected`

| Action | Allowed pipeline statuses (frontend) |
|--------|--------------------------------------|
| Approve (queue) | `exception`, `duplicate_skipped`, `rejected` |
| Approve (drawer) | `exception` only (not rejected/duplicate) |
| Reject | `exception`, `processed` |
| Reprocess | `exception`, `duplicate_skipped`, `processed`, `rejected` |

Source: `frontend/src/lib/invoiceActions.ts`

---

## 2. End-to-end processing order (gates)

Primary orchestrator: `backend/app/services/invoice/pipeline.py`  
Early phases: `backend/app/services/invoice/invoice_pipeline_phases.py`

| # | Phase | Pass criteria | Fail outcome | Skip on reprocess? |
|---|-------|---------------|--------------|--------------------|
| 1 | Storage verify | File readable at stored path | OCR fail / `stored_file_missing` | No |
| 2 | File validity | Type, size, encryption, corruption | `exception` + rejection code | No |
| 3 | Vision understand | Vision LLM can read the document (`can_understand` + confidence floor) | **Branch:** cannot → continue present IQ/OCR path; can → vision header extract | No |
| 3a | Vision header extract (can-understand only) | Printed `document_heading`, LLM `canonical_document_type`, org-aware counterparty → `vendor`, refs, `invoice_date`, `total`, `currency` persisted; vault relocate via `sync_vision_header_vault_path` (type-as-book → vendor) | On success or fail: `exception` + `awaiting_classification` + `vision_path_pending` (`header_extracted_awaiting_dt`); no legacy OCR | No |
| 4 | Image quality (pre-OCR) | Visual fitness; severe only rejects | `exception` + `needs_rescan` | No (warn continues) |
| 5 | Layout readiness | Route OCR mode / DI fallback hints | Never rejects (route only) | No |
| 6 | OCR | Layout/read succeeds (honors readiness) | OCR failure | No |
| 7 | OCR quality confirm | Not sparse / enough chars / quality OK | `exception` + `needs_rescan` | `image_quality` |
| 8 | LLM classify | Suggested DT + confidence | Continues to gate | — |
| 9 | Heading reconcile | Heading may override / clear LLM DT | May clear suggested DT | — |
| 10 | Policy backfill | Classifier winner ≥ route min | — | — |
| 11 | Classification gate | Confidence + recognition mode | `exception` + `awaiting_classification` | `classification` |
| 12 | Field extract | DI + LLM + layout merge | — | — |
| 13 | Field confidence | Playbook required fields ≥ floor | `needs_review` / hold path | `field_confidence` |
| 14 | Vendor drift (if applicable) | Within drift tolerance | Review signal | `vendor_drift` |
| 15 | Playbook gates | Bundle / linkage / required fields | Hold / VR-PB02 | `playbook` |
| 16 | Validation | `all_passed` | `exception` | `validation` |
| 17 | Vendor registration | Known or policy allows | `pending_vendor` / unmatched expense | `vendor_registration` |
| 18 | Approval gate | Mode + match cleanliness | `pending_approval` | — |
| 19 | Match variance | Variance approved or none | `exception` (variance unapproved) | — |
| 20 | Mapping → journal → reconcile | Control accounts balanced | `exception` | `mapping_review`, `line_gl_mapping` |
| 21 | Processed | Clean completion | `status=processed` | — |

**Skippable override keys** (`processing_overrides.skip_steps`):  
`image_quality`, `classification`, `field_confidence`, `vendor_drift`, `playbook`, `validation`, `mapping_review`, `vendor_registration`, `line_gl_mapping`

Source: `backend/app/services/invoice/processing_override_catalog.py`

---

## 3. BR-FV — File validity (pre-OCR)

| Rule | Default | Pass | Fail code |
|------|---------|------|-----------|
| BR-FV-01 Allowed suffix | `.pdf`, `.jpg`, `.jpeg`, `.png`, `.docx` | Suffix in set | `unsupported_file_type` |
| BR-FV-02 Max size | **25 MB** (`MAX_UPLOAD_FILE_BYTES`) | size ≤ max | `file_too_large` |
| BR-FV-03 Max PDF pages | **200** (`MAX_UPLOAD_PDF_PAGES`) | pages ≤ max | size/page rejection path |
| BR-FV-04 Empty file | — | Non-empty | `file_empty` |
| BR-FV-05 Encrypted | — | Readable | `file_encrypted` |
| BR-FV-06 Corrupted | — | Parses | `file_corrupted` |

Source: `backend/app/services/invoice/file_validity_gate.py`, `backend/app/config.py`

### Suggested test cases

| ID | Input | Expected |
|----|-------|----------|
| TC-FV-01 | Valid PDF &lt; 25 MB | Proceeds to OCR |
| TC-FV-02 | `.txt` / `.xlsx` | Reject `unsupported_file_type` |
| TC-FV-03 | File &gt; 25 MB | Reject `file_too_large` |
| TC-FV-04 | Password-PDF | Reject `file_encrypted` |
| TC-FV-05 | 0-byte upload | Reject `file_empty` |

---

## 4. BR-IQ — Pre-OCR image quality (visual fitness)

Runs **before** OCR. Cheap raster heuristics on the first N pages (`IMAGE_QUALITY_MAX_PAGES_CHECK`, default **3**).

| Rule | Default behavior | Outcome |
|------|------------------|---------|
| BR-IQ-01 Raster open | Must open as image/PDF page | `severe` → reject |
| BR-IQ-02 Blank page | Near-zero luminance variance | `severe` → reject |
| BR-IQ-03 Tiny dimensions | min edge &lt; `IMAGE_QUALITY_MIN_DIMENSION_PX` (**200**) | `severe` → reject |
| BR-IQ-04 Low approx DPI | Below `IMAGE_QUALITY_MIN_APPROX_DPI` (**72**) | warn or severe (extreme) |
| BR-IQ-05 Crop / content fill | Fill &lt; `IMAGE_QUALITY_CONTENT_FILL_MIN` | warn or severe (extreme) |
| BR-IQ-06 Mild low contrast | Below warn std, above severe std | **warn only** |
| BR-IQ-07 Skew / orientation | Mild skew / orientation_suspect | **warn only** (severe only past extreme bars) |

| Outcome | Values |
|---------|--------|
| Severe | Status `exception`, eval `needs_rescan`, gate `image_quality` |
| Warn | Continue; audit every signal with metric + threshold (calibration window) |

Source: `backend/app/services/invoice/image_quality_gate.py`, `backend/app/config.py`

---

## 4b. BR-LR — Layout readiness (pre-OCR routing)

Route-only — **never hard-rejects**.

| Signal | Route |
|--------|-------|
| Native PDF text layer (enough chars) | `ocr_mode=native_text` (prefer text-friendly path) |
| Mixed PDF (text + large embedded images) | `allow_di_fallback=true` — DI if native text incomplete/suspicious |
| Image / scan-like | `enhanced_scan` or `standard_di` |
| Photo-collage heuristic | `vision_fallback` |

Source: `backend/app/services/invoice/layout_readiness.py`

---

## 4c. BR-OQC — Post-OCR quality confirm

Runs **after** OCR. Former “image quality gate” OCR-derived checks.

Fails when **any** of:

1. `block_sparse_ocr` (default **true**) **and** OCR marked `sparse`
2. `ocr.text_length < min_chars` where `min_chars = ai_cfg.ocr_quality_min_text_chars ?? OCR_MIN_TEXT_CHARS` (**80**)
3. OCR `image_quality` ∈ `{low, poor, unreadable}`

| Outcome | Values |
|---------|--------|
| Status | `exception` |
| Eval | `needs_rescan` |
| Review reasons | `OCR_SPARSE`, `IMAGE_QUALITY_LOW` |
| Skip override | `processing_overrides.skip_steps: ["image_quality"]` |

Source: `evaluate_ocr_quality_confirm` in `invoice_pipeline_phases.py`

### Suggested test cases

| ID | Condition | Expected |
|----|-----------|----------|
| TC-IQ-01 | Clear multi-page invoice, text ≫ 80 | Gate pass |
| TC-IQ-02 | Blank / tiny raster | Pre-OCR reject `needs_rescan` |
| TC-IQ-03 | Blurry phone photo, sparse OCR | Post-OCR confirm `needs_rescan` |
| TC-IQ-04 | Mild skew / orientation | Warn + continue |
| TC-IQ-05 | Reprocess with `skip_steps: [image_quality]` | Post-OCR confirm skipped |

---

## 5. BR-CL — Classification & auto-route

### 5.1 Confidence floor

```text
route_min = max(org.auto_route_min_confidence, dt.min_route_confidence)
```

| Knob | Default |
|------|---------|
| Org `AiClassificationConfig.auto_route_min_confidence` | **0.85** |
| Global DT floor `DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN` | **0.65** |
| Env `RUNTIME_LLM_MIN_CONFIDENCE` | **0.85** |
| Env `POLICY_MIN_CONFIDENCE` | **0.65** |

**Per-DT shipped `min_route_confidence` (examples):**

| DT family | Default min |
|-----------|-------------|
| Most transactional | 0.65 |
| Supporting (e.g. DT-02, DT-16) | 0.55 |
| Informational / non-actionable / compliance (e.g. DT-22, 24, 25) | 0.85 |

Sources: `document_type_catalog.py`, `document_type_defaults.json`, `AiClassificationConfig`

### 5.2 Auto-route pass (`evaluate_confidence_gate`)

All must hold:

1. LLM classification present
2. Suggested DT non-empty
3. DT enabled in catalogue
4. `llm.confidence >= route_min`

**Fail →** `exception` + `awaiting_classification`

**Review reasons include:**  
`LLM_INVALID`, `DT_NOT_IN_CATALOGUE`, `DT_DISABLED`, `LLM_LOW_CONF`, `CLASSIFIER_RULE_MISMATCH`, `POLICY_LOW_CONF`, `DT_MISMATCH`, `NEVER_AUTO_POLICY`, `PERSPECTIVE_AMBIGUOUS`, `COUNTERPARTY_AMBIGUOUS`, …

### 5.3 Recognition modes

| Mode | Extra pass rule |
|------|-----------------|
| **Prompt** | Confirm on LLM alone (no policy agreement required) |
| **Signals** | Policy winner ≥ policy route min **and** LLM DT == policy DT; else `POLICY_LOW_CONF` / `DT_MISMATCH` |

- Heading conflict with confirmed DT → `CLASSIFIER_RULE_MISMATCH`
- Policy `posting == "conditional"` → `NEVER_AUTO_POLICY` (never auto)

Source: `classification_compare_service.py`

### 5.4 Heading override

| Rule | Behaviour |
|------|-----------|
| Body-keyword-only heading | Must **not** override LLM |
| Heading conflicts with LLM | Clear LLM suggested DT |
| Adopt heading | When LLM empty/conflicting, or heading catalogue score ≥ **0.82** and higher than LLM |
| After adopt | Heading confidence must still meet `route_min` |

### 5.5 Policy field scorer (fallback / signals)

```text
confidence = req_score×0.55 + abs_score×0.25 + ext_score×0.20
```

If `absent_fields` violated → confidence capped to `min_route_confidence - 0.01`.

### 5.6 DT score weights (org AI config defaults)

| Weight | Default |
|--------|---------|
| `dt_score_weight_rule` | 0.45 |
| `dt_score_weight_fields` | 0.30 |
| `dt_score_weight_parse` | 0.15 |
| `dt_score_weight_heading` | 0.10 |
| `dt_score_parse_fallback` | 0.6 |
| `policy_auto_correct_gap` | 0.12 |
| `policy_review_gap` | 0.05 |

### Suggested test cases

| ID | Setup | Expected |
|----|-------|----------|
| TC-CL-01 | LLM conf 0.90, DT-01 min 0.65, org 0.85 | Auto-route (0.90 ≥ 0.85) |
| TC-CL-02 | LLM conf 0.80, org 0.85 | `awaiting_classification` (`LLM_LOW_CONF`) |
| TC-CL-03 | Signals mode, LLM=DT-01, policy=DT-08 | Fail `DT_MISMATCH` |
| TC-CL-04 | Disabled DT in catalogue | Fail `DT_DISABLED` |
| TC-CL-05 | Human `POST .../classification/resolve` | Clears await; pipeline continues |
| TC-CL-06 | Reprocess skip `classification` | Gate skipped |

---

## 6. BR-EX — Extraction & field confidence

### 6.1 Merge order

`extraction_orchestrator.py` merges: Azure DI → LLM → layout KV → regex/permit/custom (with grounding / line heuristics).

### 6.2 Confidence floors

| Threshold | Default | Setting |
|-----------|---------|---------|
| Per-field extract floor | **0.65** | `min_field_extract_confidence` |
| DI field trust | **0.60** | `DI_FIELD_TRUST_MIN_CONFIDENCE` |
| DI line-item trust | **0.50** | `DI_LINE_ITEM_TRUST_MIN_CONFIDENCE` |
| LLM line-item confidence | **0.85** | line-item thresholds |
| Line-item review | **0.75** | review threshold |

Gate fields = playbook required − absent. Low DI or LLM confidence → `FIELD_CONFIDENCE_LOW` → typically `needs_review`.

### 6.3 Compulsory vs infrastructure

| Class | Behaviour |
|-------|-----------|
| Compulsory (VR03 / Rule Book stars) | Missing → validation block |
| Playbook hard required | Prefers `{vendor, permit_no, po_reference}` ∪ canonical keys |
| Infrastructure (never blocks) | `attachment_name`, `document_text` |
| Posting-critical | Intersection with registry `posting_critical` keys |

Sources: `document_type_playbook_service.py`, `field_registry.json`, `document_type_field_keys.py`

### 6.4 Feature flags (extraction)

| Flag | Default |
|------|---------|
| `USE_FIELD_REGISTRY` | false |
| `USE_CITATION_GROUNDING` | false |
| `USE_EXTRACTION_SELF_CONSISTENCY` | false |
| `USE_FIELD_FUSION` | false |
| `USE_FIELD_CONTRACT_MERGE` | false |
| `USE_COMPOSITE_ROUTING` | false |
| `EXTRACTION_GAP_FILL_ENABLED` | true |
| `RUNTIME_LLM_ENABLED` | true |

`flag_enabled_for_dt(flag, dt_code)` requires global ON **and** optional DT allowlist membership.

### Suggested test cases

| ID | Condition | Expected |
|----|-----------|----------|
| TC-EX-01 | All playbook fields ≥ 0.65 | Field confidence pass |
| TC-EX-02 | Required `total` conf 0.40 | `FIELD_CONFIDENCE_LOW` / needs_review |
| TC-EX-03 | Only `attachment_name` missing | Must **not** block as infrastructure |

---

## 7. BR-VR — Validation rules (verification)

### 7.1 Rule catalogue

| Code | Label | Group | Key logic / tolerance |
|------|-------|-------|------------------------|
| **VR03** | Compulsory fields | Completeness | Profile / DT required fields present (`field_is_present`) |
| **VR05** | Tax ID / ABN | Tax ID | Mode `format` (11 digits) or `checksum`; GSTIN/registry fallback |
| **VR07** | Currency | Currency | Must match tenant currency unless foreign w/ no GST+ABN |
| **VR08** | GST rate check | Tax | `\|gst - expected\| ≤ 0.02`; skippable if incomplete |
| **VR01** | Total = subtotal + tax | Arithmetic | Tolerance **0.01**; skippable if any null |
| **VR02** | Duplicate (multi-layer) | Duplicate | Exact/normalized **block**; fuzzy **warn** (see §10) |
| **VR09** | Line arithmetic | Arithmetic | qty×price vs amount tol **0.05**; Σ lines vs subtotal **0.05** |
| **VR11** | Date sanity | Dates | Not future; age **&gt; 365 days** fails (needs controller approval path) |
| **VR12** | Vendor master | Vendor | Must exist; not blocked/inactive/suspended/closed; tax ID match |
| **VR-PB02** | Supporting docs | Playbook | Missing PO/SO linkage or mandatory sibling DTs |
| **VR-TE01…06** | Team expenses | Team | Only when route = Team Expenses (§7.4) |

Sources: `validator.py`, `extended_validations.py`, `validation_rule_catalog.py`, `team_expense_validator.py`

### 7.2 VR03 variants (compulsory fields)

| Context | Required (default behaviour) |
|---------|------------------------------|
| Standard invoice | vendor, abn, invoice_no, invoice_date, due_date, subtotal, gst, total, line_items (+ line description & amount/unit_price); ABN waivable if acceptable GSTIN |
| PO document (`purchase_document_type=po`) | vendor, po_reference, line_items, total or subtotal |
| GRN | po_reference, line_items |
| Direct expense profile | vendor, invoice_no, total, line_items |
| DT with Rule Book stars | `vr03_compulsory_fields` for that DT |

### 7.3 Validation profiles → enabled rules

| Profile | Rules |
|---------|-------|
| **standard** | VR03, VR08, VR01, VR09, VR11, VR12 (block); VR-PB02 **off** |
| **po_goods** | Same core + **VR-PB02 on** |
| **direct_expense** | VR03; VR09/VR11 as **warn**; VR-PB02 off |
| **non_actionable** | **No rules** (empty) |
| PO/GRN purchase docs without catalogue | VR03 only |

VR02 runs as **universal duplicate** for non-PO/GRN, non-non_actionable profiles when any rules are active.

Configurable order: `VR03 → VR08 → VR01 → VR09 → VR11 → VR12 → VR-PB02`  
Saved tenant toggles win; gaps fill from profile defaults.

Source: `validation_rule_catalog.py`

### 7.4 Team expense rules (route = `Team Expenses`)

| Code | Fail when |
|------|-----------|
| **VR-TE01** | No sender **or** no employee master match |
| **VR-TE02** | MTD/QTD/YTD + claim &gt; configured cap (when cap &gt; 0) |
| **VR-TE03** | Receipt required (`require_receipt` or amount ≥ `receipt_threshold`) and no receipt file; waived if amount &lt; `auto_approve_below` |
| **VR-TE04** | Employee bank account missing |
| **VR-TE05** | Employee suspended / pending verification / non-active |
| **VR-TE06** | Amount &gt; category ledger cap |

Source: `backend/app/services/purchase/team_expense_validator.py`

### 7.5 VR10 (tax invoice wording)

Jurisdiction pack policy (`tax_invoice_policy.py`): phrase patterns + optional amount threshold. Wired via jurisdiction packs; not always in the configurable Rule Book toggle order.

### Suggested test cases

| ID | Rule | Input | Expected |
|----|------|-------|----------|
| TC-VR-01 | VR01 | subtotal 100, gst 10, total 110 | Pass |
| TC-VR-02 | VR01 | total 111 (tol 0.01) | Block fail |
| TC-VR-03 | VR08 | gst off by 0.01 | Pass (≤ 0.02) |
| TC-VR-04 | VR08 | gst off by 0.05 | Fail |
| TC-VR-05 | VR09 | line qty×price off by 0.04 | Pass |
| TC-VR-06 | VR09 | line off by 0.06 | Fail |
| TC-VR-07 | VR11 | invoice_date = tomorrow | Fail |
| TC-VR-08 | VR11 | invoice_date 400 days ago | Fail |
| TC-VR-09 | VR03 | missing invoice_no on DT-01 | Fail |
| TC-VR-10 | direct_expense + VR09 fail | severity warn | `all_passed` still true |
| TC-VR-11 | non_actionable profile | any arithmetic issue | No VR rules run |
| TC-VR-12 | VR-TE05 | employee `Pending verification` | Fail |

---

## 8. BR-PB — Playbook, matching & variance

### 8.1 Match modes

`none`, `three_way_po_grn`, `three_way_so_dn`, `two_way_po_ses`, `two_way_so_invoice`, `two_way_dn_invoice`, `two_way_grn_invoice`, `reference_invoice`, `subledger_reconcile`, `shipment`, `receipt_line`

- **PO-required modes:** `three_way_po_grn`, `two_way_po_ses`, `two_way_grn_invoice`
- **Sales-required modes:** `three_way_so_dn`, `two_way_so_invoice`, `two_way_dn_invoice`

### 8.2 Profile presets (match + approval + bundle)

| Profile | Match mode | Approval mode | Enforce bundle |
|---------|------------|---------------|----------------|
| `po_goods` | three_way_po_grn | touchless_on_clean_match | Yes |
| `ar_goods` | three_way_so_dn | touchless_on_clean_match | Yes |
| `ar_goods_2way` | two_way_dn_invoice | supervisor_on_exception | No |
| `po_services` | two_way_po_ses | touchless_on_clean_match | Yes |
| `direct_expense` | none | full_doa | No |
| `credit_adjustment` | reference_invoice | supervisor_on_exception | No |
| `debit_note` | reference_invoice | **never_touchless** | No |
| `pre_transactional` | none | full_doa | No |
| `import_dossier` | shipment | never_touchless | Yes |
| `freight_logistics` | shipment | supervisor_on_exception | No |
| `intercompany` | none | full_doa | No |
| `employee_claim` | receipt_line | manager_gate | No |
| `reconciliation` | subledger_reconcile | **no_posting** | No |
| `supporting` / `informational` / `non_actionable` / `compliance_route` | none | no_posting | No |
| `master_data` | none | never_touchless | No |
| `standard_transactional` | none | touchless_on_clean_match | No |

Source: `playbook_profile_catalog.py` → `PROFILE_PRESETS`

### 8.3 Price / qty tolerances

| Rule | Value |
|------|-------|
| Price variance % | **2%** (`PRICE_MATCH_PCT = 0.02`) |
| Price variance absolute cap | **100** (doc currency) |
| Exceeds price tol | `pct > 2%` **AND** `\|variance\| > 100` |
| Qty over-billing default | **0%** (`PurchaseMatchConfig.qty_tolerance_pct`; tenant 0–100) |

Source: `document_type_match_service.py`

### 8.4 Match outcome statuses

| Class | Outcomes |
|-------|----------|
| Blocking variance | `Qty Variance`, `Price Variance`, `Amount Variance` |
| Fail-ish | `No GRN`, `No DN`, `Routed for Approval` |
| Clean | `3-Way Match`, `2-Way Match`, `Reference Match`, `Shipment Match`, `Receipt Match` |

**Variance gate:** blocks posting when outcome ∈ variance set **and** PO/SO `variance_approved` is false; applies to GL-posting Purchase/Sales routes with PO/SO match modes.

Audit example: `three_way_match_variance_unapproved`  
Source: `match_variance_gate_service.py`

### 8.5 Bundle / VR-PB02

- Example: DT-01 `bundleMandatory`: DT-02, DT-03 (PO + GRN supporting).
- Missing linkage key (PO/SO) or missing mandatory sibling uploads → fail VR-PB02.
- Exception codes: `LINKAGE_KEY_MISSING`, `EXTRACTION_INCOMPLETE`, `BUNDLE_INCOMPLETE`.

### 8.6 GL posting applicability

**Not applicable** when:

- Purchase role is `po` or `grn`
- Sales role is `so` or `dn`
- Route is `Vault`
- DT approval mode is `no_posting`, or posting not in `{yes, conditional, down-payment}`

### Suggested test cases

| ID | Scenario | Expected |
|----|----------|----------|
| TC-PB-01 | DT-01 invoice, clean 3-way | Touchless eligible if approval mode allows |
| TC-PB-02 | Price variance 3% and abs &gt; 100 | Price Variance; hold until approved |
| TC-PB-03 | Price variance 3% but abs = 50 | Within combined tol (both conditions required) |
| TC-PB-04 | DT-01 missing GRN sibling | VR-PB02 fail / bundle incomplete |
| TC-PB-05 | Variance approved on PO | Variance gate pass |
| TC-PB-06 | debit_note profile | Always hold (`never_touchless`) |

---

## 9. BR-RT — Routing & counterparty

### 9.1 Routes

`Purchase Management`, `Sales Management`, `Expenses Management`, `Team Expenses`, `Vault`

**Priority (simplified):** confident DT route → email capture rule → sales rule → perspective=sales → purchase → expense → team → plausible PO → inferred purchase type.

DT routes only if `document_type_confidence >= min_route_confidence_for_dt`.

Source: `evaluate_invoice_routing` in `invoice_evaluation_service.py`

### 9.2 Vendor / customer detection

| Setting | Default |
|---------|---------|
| Match threshold | **70** (0–100 scale) |
| Expense hold-above | **500** |

| Route / condition | Outcome |
|-------------------|---------|
| Expenses: conf ≥ threshold or known master | OK |
| Expenses: conf &lt; threshold **and** amount ≤ 500 | `unmatched_expense_vendor` |
| Expenses: conf &lt; threshold **and** amount &gt; 500 | `pending_vendor` |
| Other payable: unknown + below threshold | `pending_vendor` |
| Team / Vault / `registration_required=False` | Never vendor-flagged |
| Sales (customer analogue) | Same pattern → `pending_vendor` |

Source: `expense_vendor_policy.py`, `VendorDetectionConfig`, `vendor_hold_service.py`

### Suggested test cases

| ID | Setup | Expected |
|----|-------|----------|
| TC-RT-01 | Expenses, unknown vendor, total 400 | `unmatched_expense_vendor` |
| TC-RT-02 | Expenses, unknown vendor, total 600 | `pending_vendor` |
| TC-RT-03 | Purchase, unknown vendor, conf 50 | `pending_vendor` |
| TC-RT-04 | Team Expenses, unknown vendor | No vendor hold |

---

## 10. BR-AP — Approval & rejection

### 10.1 DT approval gate modes

| Mode | Behaviour |
|------|-----------|
| `no_posting` | Gate returns false (no hold in this gate) |
| `manager_gate` | Returns false here (team path separate) |
| `variance_workflow` | Hold `purchase_variance_pending` unless PO variance_approved |
| `full_doa` / `never_touchless` | Always hold (reason = mode) |
| `supervisor_on_exception` | Hold unless clean touchless match satisfied |
| `touchless_on_clean_match` | Hold with `match_not_clean` unless clean match / variance approved |

**Risk holds** (any mode with flags):  
`unmatched_document`, `amount_above_threshold` (`total >= auto_approve_below`), `unverified_counterparty`.

**Bypass** if `invoice_approved` audit exists in current cycle or `human_approval_bypass`.

Source: `document_type_approval_service.apply_document_type_approval_gate`

### 10.2 Frontend approve gate

Requires Rule Book compulsory fields present when VR03 enabled for DT (`compulsoryFieldsForDocumentType` / `validateInvoiceFieldsForApproval`).

Sources: `frontend/src/lib/documentCompulsoryFields.ts`, `invoiceActions.ts`

### Suggested test cases

| ID | Mode / condition | Expected |
|----|------------------|----------|
| TC-AP-01 | `touchless_on_clean_match` + clean 3-way | No approval hold |
| TC-AP-02 | `touchless_on_clean_match` + price variance | `pending_approval` / match_not_clean |
| TC-AP-03 | `full_doa` even if clean | Always hold |
| TC-AP-04 | Approve with missing compulsory field | UI blocks approve |
| TC-AP-05 | Reject from exception | `status=rejected` |

---

## 11. BR-DUP — Duplicate / identity

| Layer | Flag / default | Effect |
|-------|----------------|--------|
| Exact / normalized / identity | `DUPLICATE_INVOICE_CHECK_ENABLED=true` | VR02 **block** |
| Fuzzy | `FUZZY_DUPLICATE_CHECK_ENABLED=false` | VR02 **warn**; amount tol **0.5%**, date window **7 days** |
| Content similarity | `CONTENT_SIMILARITY_CHECK_ENABLED=false`, threshold **0.90** | Boosts fuzzy confidence |
| File-hash unique per tenant | DB unique `uq_invoice_tenant_hash` | `duplicate_skipped` |

Sources: `validator.vr02_unique`, `config.py`, duplicate services

### Suggested test cases

| ID | Condition | Expected |
|----|-----------|----------|
| TC-DUP-01 | Same file hash re-ingest | `duplicate_skipped` |
| TC-DUP-02 | Same vendor+invoice_no exact | VR02 block |
| TC-DUP-03 | Fuzzy on, near amount/date | Warn only; `all_passed` true |

---

## 12. Exception matrix (quick reference)

| Condition | Status | Eval | Example audit |
|-----------|--------|------|---------------|
| Sparse / low OCR | exception | needs_rescan | `image_quality_gate_failed` |
| Classification fail | exception | awaiting_classification | `classification_gate_failed` |
| Field confidence low | (hold/review path) | needs_review | field confidence audit |
| Validation block | exception | (varies) | `validation_failed` |
| Vendor hold | exception | pending_vendor | `vendor_registration_hold` |
| Approval required | exception | pending_approval | `approval_required` |
| Match variance | exception | (varies) | `three_way_match_variance_unapproved` |
| Awaiting PO/SO | exception | awaiting_po / awaiting_so | purchase/sales services |
| Journal unbalanced | exception | — | journaling failures |
| Reject | rejected | — | `invoice_rejected` |
| Duplicate | duplicate_skipped | — | `duplicate_skipped` |

---

## 13. Tenant / config surfaces

| Surface | Key knobs |
|---------|-----------|
| Rule Book (tenant JSON) | document_types, AI classification, vendor detection, purchase_match, routing, CoA, validation toggles |
| `AiClassificationConfig` | auto_route 0.85, OCR chars, block_sparse, min_field_extract 0.65, drift, score weights |
| `PurchaseMatchConfig` | qty_tolerance_pct |
| `VendorDetectionConfig` | threshold 70, expense_vendor_hold_above 500 |
| Env `app/config.py` | OCR/DI/LLM/duplicate/feature flags, upload limits |
| Jurisdiction packs | tax ID, tax invoice phrases, statutory rate |
| Processing overrides | per-invoice skip gates on reprocess |
| Approval policy API | `/api/approval-policy` org DOA payload |

---

## 14. API surfaces for verification testing

| Area | Endpoints | File |
|------|-----------|------|
| Invoices | upload, reprocess, process-batch, pipeline, classification/resolve, publish | `api/invoices.py` |
| Classification review | `GET /invoices/classification-review` | same |
| Approvals | board, approve, reject, request-info | `api/approvals.py` |
| Approval policy | GET/PUT | `api/approval_policy.py` |
| Matrix | GET with status/eval filters | `api/matrix.py` |
| Purchases / Sales | two-way, variance approve | `api/purchases.py`, `api/sales.py` |
| Rule book | DT CRUD, classify preview, validation toggles | `api/rule_book.py` |
| Processing status | `GET /processing/status` | `api/processing.py` |
| Pending vendors/customers | registration release | `pending_vendors.py`, `pending_customers.py` |

---

## 15. Highest-risk regression checklist

Use these first in smoke / release testing:

1. **Classification floor:** `route_min = max(0.85, dt.min)` — conf 0.80 must hold; 0.90 must auto-route for standard DT.
2. **OCR sparse:** text &lt; 80 or sparse → `needs_rescan`.
3. **VR02 severity:** exact = block; fuzzy (when enabled) = warn only.
4. **Expenses vendor hold-above 500:** 400 → unmatched; 600 → pending_vendor.
5. **3-way price:** both **2%** and abs **&gt; 100** required to exceed tol.
6. **VR-PB02** on DT-01 / `po_goods`: missing PO/GRN sibling fails.
7. **`all_passed`:** warn failures must not block; block failures must.
8. **direct_expense:** VR09/VR11 warn; approval `full_doa` always holds.
9. **File validity:** reject `.xlsx`, &gt;25 MB, encrypted PDF before OCR spend.
10. **Reprocess skips:** each `skip_steps` key bypasses only its named gate.

---

## 16. Source index

| Concern | Primary symbols / files |
|---------|-------------------------|
| Statuses | `schemas/invoice.py` |
| Pipeline stages | `services/invoice/pipeline_stages.py` |
| Main pipeline | `services/invoice/pipeline.py` |
| Early gates | `services/invoice/invoice_pipeline_phases.py` |
| File validity | `services/invoice/file_validity_gate.py` |
| Pre-OCR image quality | `services/invoice/image_quality_gate.py` |
| Layout readiness | `services/invoice/layout_readiness.py` |
| Post-OCR quality confirm | `evaluate_ocr_quality_confirm` in `invoice_pipeline_phases.py` |
| Classification compare | `services/classification/classification_compare_service.py` |
| Playbook / bundle | `services/classification/document_type_playbook_service.py` |
| Profile presets | `services/classification/playbook_profile_catalog.py` |
| Match | `document_type_match_service.py`, `purchase_match_service.py`, `sales_match_service.py` |
| Variance gate | `services/match/match_variance_gate_service.py` |
| Approval gate | `services/classification/document_type_approval_service.py` |
| Validation | `services/rule_book/validator.py`, `validation_runner.py`, `extended_validations.py`, `validation_rule_catalog.py` |
| Routing / eval | `services/invoice/invoice_evaluation_service.py` |
| Vendor hold | `expense_vendor_policy.py`, `vendor_hold_service.py` |
| Extraction | `services/extraction/extraction_orchestrator.py` |
| Field registry | `backend/data/field_registry.json` |
| DT catalogue | `backend/data/document_types.json`, `document_type_defaults.json` |
| Config / flags | `app/config.py`, `schemas/rule_book_config.py` |
| Overrides | `services/invoice/processing_override_catalog.py` |

---

## Appendix A — Shipped DT required fields (examples)

From `document_type_defaults.json` (verify against live Rule Book for the tenant under test):

| DT | `required_fields` (shipped) | Playbook profile |
|----|-----------------------------|------------------|
| DT-01 | vendor, invoice_no, total, due_date, po_reference | po_goods |
| DT-02 | vendor, permit_no | supporting |
| DT-03 | attachment_name | supporting |
| DT-04 / DT-05 | vendor, invoice_no, total, due_date | credit_adjustment / debit_note |
| DT-08 / DT-21 | (direct expense fields) | direct_expense |
| DT-13 | [] | reconciliation |
| Supporting / info DTs | often [] or light | supporting / informational / non_actionable |

Cross-field examples commonly expected: `sum(line_items.amount) == subtotal`, `subtotal + gst == total`.

---

## Appendix B — Test case template

```text
TC-ID:
Rule ID (BR-xx / VRxx):
Preconditions: (tenant Rule Book settings, feature flags, masters)
Input document / payload:
Steps:
Expected status:
Expected evaluation_status:
Expected validation results: (code, passed, severity)
Expected audit events:
Expected review_reasons (if any):
Cleanup:
```
