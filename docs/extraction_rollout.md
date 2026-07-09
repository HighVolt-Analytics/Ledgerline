# Extraction rollout playbook

Per-flag staged rollout criteria for production extraction changes.

| Flag | Pilot org | Success metric | Rollback trigger |
|------|-----------|----------------|------------------|
| `USE_CITATION_GROUNDING` | Internal tenant | Citation pass rate ≥ baseline on golden set; supervisor_review rate ≤ +5% | Citation pass rate drops >10% vs baseline |
| `USE_FIELD_FUSION` | DT-13 only (via `EXTRACTION_FLAG_DT_ALLOWLISTS_JSON`) | Golden set scalar accuracy ≥ baseline for allowlisted DTs | Any allowlisted DT regresses >5% on golden set |
| `USE_COMPOSITE_ROUTING` | Single org | No increase in false auto_process on golden set | False auto_process on any golden doc |

## Per-DT allowlist env shape

```json
{
  "use_citation_grounding": ["DT-13", "DT-01"],
  "use_field_fusion": ["DT-13"]
}
```

Set via `EXTRACTION_FLAG_DT_ALLOWLISTS_JSON`.

## Rollout order

1. Golden eval baseline (`python scripts/eval_extraction_golden.py`)
2. Enable citation grounding for one DT
3. Enable field fusion for scalars only after disagreement telemetry review
4. Composite routing last
