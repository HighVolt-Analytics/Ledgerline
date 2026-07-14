-- DI dependency report for Foundry-primary tenants.
-- Reads field_resolution_telemetry audit events emitted after merge (measurement only).
--
-- Parameters (psql):
--   \set since '''2026-06-14'''
--   \set until '''2026-07-14'''
--
-- Or bind from application script.

WITH telemetry AS (
    SELECT
        al.id AS audit_id,
        al.tenant_id,
        al.invoice_id,
        al.created_at,
        al.detail,
        al.detail ->> 'document_ai_provider' AS document_ai_provider,
        COALESCE((al.detail -> 'di_availability' ->> 'di_available')::boolean, false) AS di_available
    FROM audit_logs al
    WHERE al.event = 'field_resolution_telemetry'
      AND al.invoice_id IS NOT NULL
      AND al.created_at >= :since::timestamptz
      AND al.created_at < :until::timestamptz
      AND COALESCE(al.detail ->> 'document_ai_provider', '') = 'azure_foundry_vision'
      AND COALESCE((al.detail ->> 'policy_reextract')::boolean, false) = false
),
latest_per_invoice AS (
    SELECT DISTINCT ON (invoice_id)
        *
    FROM telemetry
    ORDER BY invoice_id, created_at DESC
),
field_rows AS (
    SELECT
        l.tenant_id,
        l.invoice_id,
        l.di_available,
        f.key AS field_name,
        f.value ->> 'chosen_source' AS chosen_source,
        COALESCE((f.value ->> 'agreed')::boolean, false) AS agreed,
        f.value ->> 'di_value' AS di_value,
        f.value ->> 'llm_value' AS llm_value,
        f.value ->> 'chosen_value' AS chosen_value
    FROM latest_per_invoice l
    CROSS JOIN LATERAL jsonb_each(l.detail -> 'fields') AS f(key, value)
    WHERE f.key IN ('total', 'subtotal', 'gst', 'line_items', 'invoice_no', 'vendor')
),
field_stats AS (
    SELECT
        field_name,
        COUNT(*) AS invoice_count,
        COUNT(*) FILTER (WHERE di_value IS NOT NULL AND di_value <> 'null') AS di_had_value,
        COUNT(*) FILTER (WHERE llm_value IS NOT NULL AND llm_value <> 'null') AS llm_had_value,
        COUNT(*) FILTER (WHERE chosen_source = 'azure_di') AS di_chosen,
        COUNT(*) FILTER (WHERE chosen_source = 'llm') AS llm_chosen,
        COUNT(*) FILTER (WHERE chosen_source = 'fallback') AS fallback_chosen,
        COUNT(*) FILTER (WHERE agreed) AS agreed_count,
        COUNT(*) FILTER (
            WHERE NOT agreed
              AND di_value IS NOT NULL
              AND di_value <> 'null'
              AND llm_value IS NOT NULL
              AND llm_value <> 'null'
        ) AS disagreed_both_present
    FROM field_rows
    GROUP BY field_name
),
invoice_di_availability AS (
    SELECT
        COUNT(*) AS invoice_count,
        COUNT(*) FILTER (WHERE di_available) AS di_available_count
    FROM latest_per_invoice
)
SELECT
    fs.field_name,
    fs.invoice_count,
    ROUND(100.0 * fs.di_chosen / NULLIF(fs.invoice_count, 0), 2) AS pct_di_chosen,
    ROUND(100.0 * fs.llm_chosen / NULLIF(fs.invoice_count, 0), 2) AS pct_llm_chosen,
    ROUND(100.0 * fs.fallback_chosen / NULLIF(fs.invoice_count, 0), 2) AS pct_fallback_chosen,
    ROUND(100.0 * fs.agreed_count / NULLIF(fs.invoice_count, 0), 2) AS pct_agreed,
    ROUND(
        100.0 * fs.disagreed_both_present / NULLIF(fs.invoice_count, 0),
        2
    ) AS pct_disagreed_both_present,
    ROUND(100.0 * fs.di_had_value / NULLIF(fs.invoice_count, 0), 2) AS pct_di_had_value,
    fs.di_chosen,
    fs.llm_chosen,
    fs.fallback_chosen,
    fs.agreed_count,
    fs.disagreed_both_present
FROM field_stats fs
ORDER BY fs.field_name;

-- DI availability summary (run as second query in application script)
-- SELECT * FROM invoice_di_availability;
