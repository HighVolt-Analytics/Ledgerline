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
    'email_verification_otp'
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

-- App role (optional — migrations use owner role)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ledgerlink_app') THEN
    CREATE ROLE ledgerlink_app LOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO ledgerlink_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ledgerlink_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledgerlink_app;
