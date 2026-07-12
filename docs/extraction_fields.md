# Extraction fields (field contracts)

Extraction fields are no longer only an LLM prompt list. They are **per-field contracts** that control what is requested, where values may come from, how they are trusted, and where they are persisted.

## Pipeline (unchanged order)

OCR → classify → route → DI enrich → LLM extract → **merge (contracts or legacy)** → review → persist

Entry points (`process_invoice`, `extract_fields`, `InvoiceData`) are unchanged.

## Resolving contracts

`resolve_extraction_field_contracts_for_dt` builds contracts from:

1. Org `extraction_fields` / `required_fields` (explicit wins)
2. Route defaults (`ExtractionRoute` → key set)
3. Shipped template defaults (only if org row still matches shipped title/template)
4. Playbook recommended keys (transactional routes)
5. Commercial fallback (invoice/credit/debit/receipt/expense only)
6. Supporting / unknown stay empty unless org-configured

Helpers `configured_extraction_keys` / `effective_extraction_field_keys_for_dt` / `_selected_keys_for_dt` are thin adapters over contracts.

## Field resolution

With `USE_FIELD_CONTRACT_MERGE=true`, merge collects candidates per field from:

- semantic DI (`invoice_fields`)
- layout KV
- regex / local parse
- LLM
- layout/DI line items (for `line_items`)

Then `resolve_field_value`:

1. Filter by allowed sources  
2. Apply confidence threshold (DI)  
3. Grounding when required  
4. Normalize / validate  
5. Pick by authoritative source order  

Projection:

- Canonical keys → `InvoiceData` columns (`vendor`, `abn`, `currency`, `cost_centre`, …)
- Custom / extracted-only → `extracted_fields`
- `abn` also keeps `seller_abn` evidence in `extracted_fields`

## LLM payload

Still sends `extraction_fields` + manifests. Also may include:

- `required_fields` (from contracts)
- `field_source_hints` (custom fields / label aliases only)

Rule remains: **Extract ONLY listed fields**.

## OCR persistence

- DI enrich upserts onto the OCR artifact (including after DT re-extract).
- Upsert replaces structured line-item / grid keys and stores `field_resolution` when present.
- Full reprocess still clears OCR cache.

## Feature flag

```env
USE_FIELD_CONTRACT_MERGE=false   # default: legacy layered merge
# USE_FIELD_CONTRACT_MERGE=true  # field-contract merge
```

## Debugging a missing field

1. Confirm the DT/route contract includes the key (`selected_keys` / Rule Book `extraction_fields`).
2. Check OCR payload `invoice_fields` / `layout_kv` / text for evidence.
3. Inspect `field_resolution` (OCR payload or `InvoiceData.raw_fields`) for status, chosen source, rejected candidates.
4. If status is `missing`, the field was never requested or no candidate passed trust rules.

## Code map

| Concern | Module |
|---|---|
| Models | `app.services.extraction.field_contracts` |
| Templates / route defaults | `app.services.extraction.field_registry` |
| Contract resolution | `app.services.extraction.field_contract_resolver` |
| Resolve / project | `app.services.extraction.field_resolvers` |
| Validators | `app.services.extraction.field_validators` |
| Merge swap | `extraction_orchestrator.merge_extraction_sources` |

## Migration / compatibility

- Flag off → previous layered merge behavior.
- Flag on → contract merge; same `InvoiceData` consumers.
- No DB migration; additive OCR/audit metadata only.
- Future Azure query fields: set `query_field_name` on a contract without redesigning merge.
