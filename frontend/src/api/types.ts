export interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
}

/** @deprecated use Tenant */
export type Organisation = Tenant;

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  currency: string;
  is_current: boolean;
}

export interface PlatformTenantModule {
  module_key: string;
  is_active: boolean;
}

export interface PlatformTenantSummary {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  lifecycle_status: string;
  created_at: string | null;
  user_count: number;
  invoice_count: number;
  credit_balance: number;
}

export interface PlatformTenantDetail extends PlatformTenantSummary {
  settings_json: Record<string, unknown> | null;
  modules: PlatformTenantModule[];
}

export interface TenantMembership {
  user_id: number;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  role: string;
  default_tenant?: boolean;
  is_platform?: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUser;
  memberships?: TenantMembership[];
}

export interface ConnectedMailbox {
  id: number;
  tenant_id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  auth_type: "application" | "delegated" | string;
  connection_status: "connected" | "disconnected" | "error" | string;
  oauth_connected_at: string | null;
  last_error: string | null;
  last_poll_at: string | null;
}

export interface MailboxBackfillJob {
  id: number;
  tenant_id: string;
  mailbox_id: number;
  from_date: string;
  to_date: string;
  mark_processed: boolean;
  status: "queued" | "running" | "completed" | "failed" | string;
  messages_scanned: number;
  attachments_ingested: number;
  messages_skipped: number;
  invoices_processed: number;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface MailboxBackfillQueued {
  job: MailboxBackfillJob;
  task_id: string;
}

export interface MailboxConnectionRequest {
  id: number;
  tenant_id: string;
  requested_email: string;
  display_name: string | null;
  message: string | null;
  status: "pending" | "connected" | "expired" | "cancelled" | string;
  invite_sent_at: string | null;
  expires_at: string | null;
  connected_at: string | null;
  connected_mailbox_id: number | null;
  created_at: string;
}

export interface MailboxConnectionRequestAction extends MailboxConnectionRequest {
  connect_url: string;
  email_sent: boolean;
  email_error: string | null;
}

export interface MailboxInvitePreview {
  tenant_name: string;
  requested_email: string;
  display_name: string | null;
  message: string | null;
  expires_at: string | null;
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
  meta: {
    page: number;
    total: number;
    pages: number;
    segment_count?: number | null;
    segment_invoice_ids?: number[] | null;
  };
}

export type UploadInvoiceResult = {
  invoice: Invoice;
  segmentCount: number;
  segmentInvoiceIds: number[];
};

export interface ValidationResult {
  rule: string;
  passed: boolean;
  message: string;
  skipped: boolean;
}

export interface Invoice {
  id: number;
  document_ref?: string | null;
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
  capture_source: string | null;
  connected_mailbox_id: number | null;
  storage_vendor_slug: string | null;
  account_code: string | null;
  account_name: string | null;
  route_target: string | null;
  matched_rule_ids: string[] | null;
  vendor_confidence: number | null;
  evaluation_status:
    | "auto_coded"
    | "needs_review"
    | "pending_vendor"
    | "unmatched_expense_vendor"
    | "awaiting_po"
    | null;
  validation_results: ValidationResult[] | null;
  purchase_document_type?: string | null;
  document_type_code?: string | null;
  document_type_confidence?: number | null;
  document_type_extraction_fields?: string[] | null;
  bank_bsb?: string | null;
  bank_account?: string | null;
  email_attachment_name?: string | null;
  billing_address?: string | null;
  email_subject?: string | null;
  document_text?: string | null;
  extraction_field_confidence?: Record<string, number> | null;
  created_at: string;
  has_stored_file: boolean;
  published_to_ledger?: boolean;
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
  business_expenses_count: number;
  payments_queue_count: number;
  integrations_connected: number;
}

export interface ThreeWayMatchApi {
  status: string;
  qty_variance_value: number;
  price_variance_value: number;
  total_deviation: number;
  po_value: number;
  invoice_value: number;
  invoice_gst: number;
  invoice_total: number;
}

export interface PurchaseDossierMember {
  role: string;
  label: string;
  invoice_id: number | null;
  document_ref: string | null;
  present: boolean;
  has_stored_file: boolean;
  is_current: boolean;
}

export interface PurchaseDossier {
  po_reference: string | null;
  current_role: string | null;
  members: PurchaseDossierMember[];
  purchase_order_id: number | null;
  match: ThreeWayMatchApi | null;
  match_status: string | null;
}

export interface PurchaseOrderApi {
  id: number;
  po_number: string;
  vendor: string | null;
  po_date: string | null;
  item: string | null;
  requestor: string | null;
  po_qty: number;
  po_unit_price: number;
  grn_qty: number | null;
  grn_date: string | null;
  grn_receiver: string | null;
  grn_condition: string | null;
  invoice_id: number | null;
  po_document_id?: number | null;
  grn_document_id?: number | null;
  invoice_no: string | null;
  invoice_qty: number;
  invoice_unit_price: number;
  gst_rate: number;
  variance_approved: boolean;
  status: string;
  three_way_match_status?: "full_match" | "partial" | "mismatch" | null;
  match: ThreeWayMatchApi;
  route_target?: string | null;
  evaluation_status?: string | null;
  matched_rule_ids?: string[];
  matched_rule_name?: string | null;
  matched_gl?: string | null;
  ledger?: string | null;
  sub_ledger?: string | null;
  purchase_rule_id?: string | null;
}

export interface PaymentApi {
  id: number;
  invoice_id: number;
  vendor: string | null;
  amount: number;
  currency: string;
  status: string;
  tab: string;
  due_date: string | null;
  scheduled_date: string | null;
  paid_date: string | null;
  invoice_approved_by: number | null;
  approvers: Array<Record<string, unknown>>;
  payment_intent: string | null;
  failure_reason: string | null;
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
  summary?: string | null;
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
  whatsapp_configured: boolean;
}

export interface WhatsappConnection {
  id: number;
  tenant_id: string;
  phone_number_id: string;
  phone_number: string | null;
  display_name: string | null;
  whatsapp_business_account_id: string | null;
  connection_status: string;
  integration_health: string;
  last_error: string | null;
  last_sync_at: string | null;
  connected_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface WhatsappStatus {
  configured: boolean;
  webhook_callback_url: string;
  oauth_callback_url: string;
  connections: WhatsappConnection[];
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
    priority?: number;
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
    priority?: number;
    match_on: Record<string, unknown>;
    post_to: { ledger: string; sub_ledger: string };
    matched_count: number;
  }>;
  team_expense_rules: Array<{
    id: string;
    name: string;
    enabled: boolean;
    priority?: number;
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
  document_classification?: {
    unclassified_document_type_code: string;
    unclassified_min_confidence: number;
  };
  document_types: Array<{
    code: string;
    title: string;
    short_title: string;
    klass: string;
    posting: string;
    fraud_risk: string;
    one_line: string;
    route_target: string;
    enabled: boolean;
    classifier: {
      enabled: boolean;
      priority: number;
      confidence: number;
      root: Record<string, unknown>;
    };
    validation_profile?: string;
    playbook_profile?: string;
    match_policy?: { mode: string };
    approval_policy?: { mode: string };
    validation_rules?: Array<{
      code: string;
      enabled: boolean;
      severity: "block" | "warn";
    }>;
    custom_validation_rules?: Array<{
      id: string;
      name: string;
      field: string;
      operator: "present" | "absent" | "contains" | "not_contains" | "gte" | "lte";
      value: string;
      enabled: boolean;
      severity: "block" | "warn";
    }>;
    required_fields?: string[];
    absent_fields?: string[];
    min_route_confidence?: number;
    extraction_fields?: string[];
    extraction: string[];
    checks: string[];
    match: string[];
    approval: string[];
    accounting: string[];
    special: string[];
    bundle_mandatory: string[];
    bundle_conditional: string[];
    purchase_bundle_role?: string;
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
    document_type_code?: string | null;
  };
  email_rule: { id: string; name: string } | null;
  email_rule_disabled: { id: string; name: string } | null;
  vendor_match: { vendor_id: string; vendor_name: string; confidence: number } | null;
  category_rule: { label: string; kind: string } | null;
  category_rule_disabled: { label: string; kind: string } | null;
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
  book: string;
  document_type?: string | null;
  vendor: string;
  year: string;
  month: string;
  po_folder?: string | null;
  purchase_document_type?: string | null;
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
  when?: string | null;
  detail?: string | null;
}

export interface MatrixConflictRow {
  field: string;
  this_doc: string;
  other_doc: string;
}

export interface MatrixRow {
  invoice: Invoice;
  stages: MatrixStageCell[];
  flag: string;
  flag_reason?: string | null;
  payment_status: string;
  conflict_with?: string | null;
  conflict_detail?: MatrixConflictRow[] | null;
}

export interface LedgerExportRow {
  id: string;
  doc: string;
  date: string;
  party: string;
  debit: string;
  credit: string;
  amount: number;
  status: string;
}

export interface LedgerLinkExports {
  invoices: LedgerExportRow[];
  bills: LedgerExportRow[];
  expenses: LedgerExportRow[];
  purchases: LedgerExportRow[];
  payments: LedgerExportRow[];
}

export interface LedgerLinkResponse {
  overview: ReconciliationOverview;
  exports: LedgerLinkExports;
}

export interface WalletTransaction {
  id: string;
  label: string;
  delta: number;
}

export interface WalletSummary {
  balance: number;
  available: number;
  last_top_up: string;
  transactions: WalletTransaction[];
}

export interface CreditPack {
  id: string;
  name: string;
  credits: number;
  price_aud: number;
  popular?: boolean;
}

export interface BillingState {
  balance: number;
  current_pack: string;
  auto_recharge: boolean;
  threshold: number;
  packs: CreditPack[];
}

export interface PipelineAuditStep {
  stage: string;
  at: string | null;
  when: string;
  detail: string;
  state: "done" | "pending" | "fail" | "skipped";
}

export interface InvoiceClassificationScoreBreakdown {
  rule_strength?: number;
  field_completeness?: number;
  parse_score?: number;
  heading_alignment?: number;
  required_present?: string[];
  required_missing?: string[];
  absent_ok?: string[];
  absent_violations?: string[];
  signal_conflicts?: string[];
}

export interface InvoiceClassificationAudit {
  document_type_code?: string;
  document_type_confidence?: number;
  document_type_title?: string | null;
  document_type_klass?: string | null;
  reason?: string;
  needs_review?: boolean;
  min_route_confidence?: number;
  signal_conflicts?: string[];
  score_breakdown?: InvoiceClassificationScoreBreakdown;
}
