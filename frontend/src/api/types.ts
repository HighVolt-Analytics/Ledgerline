export interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  org_id: number;
  org_name: string;
  org_slug: string;
}

export interface Organisation {
  id: number;
  name: string;
  slug: string;
  currency: string;
  is_current: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface ConnectedMailbox {
  id: number;
  org_id: number;
  email: string;
  display_name: string | null;
  is_active: boolean;
  last_poll_at: string | null;
}

export interface ProcessingStatus {
  state: string;
  last_run: string | null;
  active_tasks: number;
}

export type InvoiceStatus =
  | "pending"
  | "parsing"
  | "validating"
  | "mapping"
  | "journaling"
  | "reconciling"
  | "processed"
  | "exception"
  | "duplicate_skipped"
  | "rejected";

export interface ApiEnvelope<T> {
  data: T;
  error: { code: string; message: string } | null;
  meta: { page: number; total: number; pages: number };
}

export interface ValidationResult {
  rule: string;
  passed: boolean;
  message: string;
  skipped: boolean;
}

export interface Invoice {
  id: number;
  vendor: string | null;
  abn: string | null;
  invoice_no: string | null;
  po_reference: string | null;
  cost_centre: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string;
  subtotal: string | null;
  gst: string | null;
  total: string | null;
  status: InvoiceStatus;
  file_hash: string | null;
  raw_file_path: string | null;
  email_sender: string | null;
  connected_mailbox_id: number | null;
  storage_vendor_slug: string | null;
  account_code: string | null;
  account_name: string | null;
  route_target: string | null;
  matched_rule_ids: string[] | null;
  vendor_confidence: number | null;
  evaluation_status: "auto_coded" | "needs_review" | "pending_vendor" | null;
  validation_results: ValidationResult[] | null;
  created_at: string;
  has_stored_file: boolean;
}

export interface LineItem {
  id: number;
  invoice_id: number;
  description: string | null;
  qty: string | null;
  unit_price: string | null;
  amount: string | null;
  tax_amount: string | null;
}

export interface JournalEntry {
  id: number;
  invoice_id: number;
  date: string;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
  entry_type: string;
}

export interface InvoiceDetails extends Invoice {
  line_items: LineItem[];
  journal_entries: JournalEntry[];
}

export interface LineItemUpdatePayload {
  id?: number;
  description?: string | null;
  qty?: string | null;
  unit_price?: string | null;
  amount?: string | null;
  tax_amount?: string | null;
}

export interface InvoiceUpdatePayload {
  vendor?: string | null;
  abn?: string | null;
  invoice_no?: string | null;
  po_reference?: string | null;
  cost_centre?: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  subtotal?: string | null;
  gst?: string | null;
  total?: string | null;
  account_code?: string | null;
  account_name?: string | null;
  line_items?: LineItemUpdatePayload[];
}

export interface NavBadges {
  inbox_count: number;
  pending_approval: number;
  team_expenses_count: number;
  payments_queue_count: number;
  integrations_connected: number;
}

export interface DashboardStats {
  total_invoices: number;
  invoices_this_month: number;
  processed: number;
  exceptions: number;
  pending: number;
  inbox_count: number;
  duplicates_skipped: number;
  rejected: number;
  pending_approval: number;
  base_currency: string;
  total_value: string | number;
  value_by_currency: Record<string, string | number>;
  total_value_aud: string | number;
  synced_percent: number;
  avg_processing_seconds: number | null;
  last_reconciliation_balanced: boolean | null;
  reconciliation_delta_dr_cr: string | number | null;
  integrations_connected: number;
  distinct_vendors: number;
  docs_via_email: number;
  docs_via_upload: number;
  mailboxes_mapped: number;
  active_users: number;
}

export interface ActivityItem {
  id: number;
  invoice_id: number | null;
  event: string;
  detail: Record<string, unknown> | null;
  created_at: string;
  vendor: string | null;
  status: InvoiceStatus | null;
}

export interface TopVendorRow {
  vendor: string;
  amount: string | number;
  invoice_count: number;
}

export interface CashForecastBucket {
  label: string;
  amount: string | number;
}

export interface MailboxBreakdownRow {
  mailbox_id: number;
  email: string;
  display_name: string | null;
  is_active: boolean;
  last_poll_at: string | null;
  document_count: number;
}

export interface AnomalyRow {
  tag: string;
  description: string;
  invoice_id: number | null;
}

export interface KpiTrend {
  direction: "up" | "down" | "flat";
  text: string;
  favorable: boolean | null;
}

export interface KpiSparklines {
  invoice_volume: number[];
  docs_via_email: number[];
  docs_via_upload: number[];
  total_value: number[];
  distinct_vendors: number[];
  mailboxes_active: number[];
  active_users: number[];
  avg_processing_seconds: number[];
  reconciliation_delta: number[];
}

export interface DashboardOverview {
  period: string;
  period_has_data: boolean;
  cash_forecast_scope: string;
  stats: DashboardStats;
  activity: ActivityItem[];
  top_vendors: TopVendorRow[];
  cash_forecast: CashForecastBucket[];
  mailbox_breakdown: MailboxBreakdownRow[];
  anomalies: AnomalyRow[];
  kpi_trends: Record<string, KpiTrend>;
  kpi_sparklines: KpiSparklines;
  integrations_connected: number;
  invoice_volume_sparkline: number[];
}

export interface ReportDocumentRow {
  id: number;
  document_ref: string;
  vendor: string;
  account: string;
  invoice_date: string | null;
  period_key: string;
  subtotal: number | string;
  gst: number | string;
  total: number | string;
  currency: string;
}

export interface GlAccountSpendRow {
  account: string;
  amount: number | string;
  count: number;
}

export interface VendorSpendRow {
  vendor: string;
  amount: number | string;
  count: number;
}

export interface ReportsKpiTrends {
  net_spend_delta_pct: number | null;
  tax_delta_pct: number | null;
  gross_spend_delta_pct: number | null;
  documents_delta: number | null;
}

export interface ReportsAnalytics {
  base_currency: string;
  tax_label: string;
  period_key: string;
  period_label: string;
  net_spend: number | string;
  tax_total: number | string;
  gross_spend: number | string;
  document_count: number;
  by_gl_account: GlAccountSpendRow[];
  top_vendors: VendorSpendRow[];
  kpi_trends: ReportsKpiTrends;
  period_has_data: boolean;
}

export interface Vendor {
  id: number;
  vendor_slug: string;
  vendor_name: string;
  sender_pattern: string;
  abn: string | null;
  approved: boolean;
}

export interface AppSettings {
  graph_mailbox: string;
  graph_enabled: boolean;
  graph_poll_interval_minutes: number;
  graph_folder_moves_enabled: boolean;
  graph_processed_folder: string;
  graph_exceptions_folder: string;
  blob_enabled: boolean;
  azure_storage_container: string;
  azure_di_enabled: boolean;
  azure_postgres_enabled: boolean;
  azure_redis_enabled: boolean;
  appinsights_enabled: boolean;
  azure_location: string;
  azure_webapp_url: string;
  abn_validation_mode: string;
  rule_book_config_path: string;
  cors_origins: string;
}

export interface DocumentSetRule {
  id: string;
  pattern: string;
  set_name: string;
  isolated?: boolean;
}

export interface DocumentCodeRule {
  id: string;
  pattern: string;
  account: string;
  isolated?: boolean;
}

export interface RuleBook {
  priority_order?: string[];
  po_codes: Record<string, string>;
  po_code_isolated?: Record<string, boolean>;
  doc_codes?: DocumentCodeRule[];
  vendors: Record<string, string>;
  vendor_isolated?: Record<string, boolean>;
  keywords: Record<string, string>;
  keyword_isolated?: Record<string, boolean>;
  doc_sets?: DocumentSetRule[];
  tax_account: string;
  payable_account: string;
  fallback_account: string;
}

/** API payload for GET/PUT /api/rule-book/config (snake_case). */
export interface RuleBookConfig {
  schema_version: number;
  email_capture_rules: Array<{
    id: string;
    name: string;
    enabled: boolean;
    priority: number;
    mailbox: string;
    root: Record<string, unknown>;
    action: {
      save_attachment: boolean;
      route_to: string;
      tags: string[];
    };
    matched_count: number;
    last_matched: string;
  }>;
  purchase_rules: Array<{
    id: string;
    name: string;
    enabled: boolean;
    match_on: Record<string, unknown>;
    post_to: {
      ledger: string;
      sub_ledger: string;
      tax_account?: string;
      payable_account?: string;
    };
    matched_count: number;
  }>;
  expense_rules: Array<{
    id: string;
    name: string;
    enabled: boolean;
    match_on: Record<string, unknown>;
    post_to: { ledger: string; sub_ledger: string };
    matched_count: number;
  }>;
  team_expense_rules: Array<{
    id: string;
    name: string;
    enabled: boolean;
    match_on: Record<string, unknown>;
    post_to: { ledger: string; sub_ledger: string };
    policy: {
      require_receipt: boolean;
      receipt_threshold: number;
      auto_approve_below: number;
    };
    matched_count: number;
  }>;
  vendor_masters: Array<Record<string, unknown>>;
  vendor_detection_config: {
    weights: { name: number; abn: number; bank: number; address: number };
    threshold: number;
  };
  employee_masters: Array<Record<string, unknown>>;
  posting_defaults: {
    tax_account: string;
    payable_account: string;
    fallback_account: string;
  };
  document_sets: Array<{
    id: string;
    pattern: string;
    set_name: string;
    isolated?: boolean;
  }>;
}

export type RuleBookRulesPayload = Omit<
  RuleBookConfig,
  "vendor_masters" | "employee_masters"
>;

export interface RuleBookEvaluationRow {
  document: {
    id: string;
    doc_number: string;
    invoice_no: string;
    vendor: string;
    primary_account: string;
  };
  email_rule: { id: string; name: string } | null;
  email_rule_disabled: { id: string; name: string } | null;
  vendor_match: { vendor_id: string; vendor_name: string; confidence: number } | null;
  category_rule: { label: string; kind: string } | null;
  auto_coded: boolean;
}

export interface RuleBookEvaluateResult {
  source: "invoices" | "sample";
  rows: RuleBookEvaluationRow[];
}

export interface RuleBookEvaluateRequest {
  config?: RuleBookRulesPayload;
  invoice_ids?: number[];
  limit?: number;
}

export interface DailyReconciliation {
  date: string;
  total_invoices: number;
  total_ap_credits: string;
  total_debits: string;
  total_credits: string;
  rc1_passed: boolean;
  rc2_passed: boolean;
  is_balanced: boolean;
  halted: boolean;
  halt_reason: string | null;
}

export interface ReconciliationJournalLine {
  id: number;
  invoice_id: number;
  vendor: string | null;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
  entry_type: string;
}

export interface ReconciliationDayDetail {
  date: string;
  invoices_total: string;
  total_debits: string;
  total_credits: string;
  delta_dr_cr: string;
  delta_vs_invoices: string;
  rc1_passed: boolean;
  rc2_passed: boolean;
  is_balanced: boolean;
  halt_reason: string | null;
  journal_lines: ReconciliationJournalLine[];
  invoices: Array<{
    id: number;
    vendor: string | null;
    invoice_no: string | null;
    total: string | null;
  }>;
}

export interface ReconPostingRow {
  account: string;
  debit: string | number;
  credit: string | number;
}

export interface ReconInvoiceOverviewRow {
  id: string;
  invoice_id: number;
  vendor: string;
  total: string | number;
  postings: ReconPostingRow[];
}

export interface ReconDayOverviewRow {
  date: string;
  count: number;
  sum_dr: string | number;
  sum_cr: string | number;
  delta: string | number;
  invoices: ReconInvoiceOverviewRow[];
}

export interface ReconciliationOverview {
  sum_totals: string | number;
  sum_dr: string | number;
  sum_cr: string | number;
  delta_dr_cr: string | number;
  balanced: boolean;
  base_currency: string;
  by_date: ReconDayOverviewRow[];
}

export interface VaultTreeNode {
  id: string;
  label: string;
  kind: string;
  count: number;
  children: VaultTreeNode[];
}

export interface VaultApiFile {
  invoice_id: number;
  org: string;
  vendor: string;
  year: string;
  month: string;
  file_name: string;
  virtual_path: string;
  blob_path: string | null;
  has_stored_file: boolean;
}

export interface VaultTreeResponse {
  tree: VaultTreeNode[];
  files: VaultApiFile[];
  blob_enabled: boolean;
}

export interface VaultMigrateResponse {
  moved: number;
  skipped: number;
  blob_enabled: boolean;
}

export interface AuditLogEntry {
  id: number;
  correlation_id: string | null;
  event: string;
  invoice_id: number | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface RuleBookChangelogEntry {
  id: number;
  event: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface PolicyRule {
  id: string;
  condition: string;
  approver: string;
}

export interface ApprovalPolicy {
  locked: boolean;
  rules: PolicyRule[];
  matrix: Record<string, Record<string, boolean>>;
}

export type MatrixCellState = "done" | "pending" | "fail";

export interface MatrixStageCell {
  stage: string;
  state: MatrixCellState;
}

export interface MatrixRow {
  invoice: Invoice;
  stages: MatrixStageCell[];
}

export interface PipelineAuditStep {
  stage: string;
  at: string | null;
  when: string;
  detail: string;
  state: "done" | "pending" | "fail" | "skipped";
}
