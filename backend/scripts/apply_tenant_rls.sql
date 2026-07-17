-- PostgreSQL RLS for tenant isolation (idempotent).
-- Run after alembic upgrade 029: python scripts/run_rls.py

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'users', 'invoices', 'vendor_registry', 'vendor_masters', 'employee_masters',
    'pending_vendors', 'purchase_orders', 'payments', 'connected_mailboxes',
    'connected_whatsapp_accounts', 'mailbox_connection_requests', 'mailbox_sync_jobs',
    'audit_logs', 'daily_reconciliations', 'user_tenant_mappings', 'tenant_modules',
    'email_verification_otp', 'tenant_member_invites', 'tenant_rule_book_configs',
    'line_items', 'journal_entries', 'goods_receipts', 'meta_webhook_dedupe',
    'dossier_manual_links',
    'stripe_accounts', 'stripe_balance_snapshots', 'stripe_transactions', 'vendor_payment_methods',
    'tenant_payment_provider_accounts', 'provider_transactions', 'payment_attempts',
    'invoice_ocr_artifacts', 'classification_learning_events',
    'accounting_integrations',
    'accounting_sync_jobs',
    'xero_connections',
    'xero_accounts',
    'xero_tax_rates',
    'xero_contacts',
    'xero_currencies',
    'xero_webhook_events',
    'external_accounting_refs',
    'connected_viber_accounts', 'payment_execution_instructions',
    'customer_masters', 'customer_registry', 'sales_orders', 'delivery_notes', 'collections'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = t
    ) THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
      IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = t AND policyname = 'tenant_isolation'
      ) THEN
        EXECUTE format(
          'CREATE POLICY tenant_isolation ON %I
           USING (
             tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid
           )
           WITH CHECK (
             tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid
           )',
          t
        );
      END IF;
    END IF;
  END LOOP;
END $$;

-- App role (optional â€” migrations use owner role)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ledgerlink_app') THEN
    CREATE ROLE ledgerlink_app LOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO ledgerlink_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ledgerlink_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledgerlink_app;

