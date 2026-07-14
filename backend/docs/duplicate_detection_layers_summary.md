# Duplicate detection — 7-layer stack (stakeholder summary)

| Layer | Mode | Flag default | Status |
|-------|------|--------------|--------|
| L1 Exact (file hash / invoice#+vendor) | Hard block | always on | done |
| L2 Field normalization | Improves matching | always on | done |
| L3 Vendor identity report | Report-only | always on as report | done (FK migration proposal only) |
| L4 Fuzzy business match | Review warn | `FUZZY_DUPLICATE_CHECK_ENABLED=false` | done |
| L5 Content similarity | Boosts L4 confidence | `CONTENT_SIMILARITY_CHECK_ENABLED=false` | done |
| L6 Cross-channel gap | Audit only | n/a | done (fix held) |
| L7 Reviewer feedback | Infra | always on | done |

**Blocking automatically:** identical files, exact/normalized identity (VR02 block).  
**Flagging for review:** fuzzy (±0.5% / ±7d) when enabled — severity warn + confidence.  
**Report-only:** probable duplicate vendors; cross-channel residual gap; FP rate script.
