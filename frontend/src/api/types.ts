export interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  tenant_timezone: string;
  tenant_locale: string;
  is_support_session?: boolean;
  onboarding_completed?: boolean;
}

export type ApprovalActionKey =
  | "View"
  | "Comment"
  | "Approve"
  | "Reject"
  | "Post"
  | "Edit Policy"
  | "Manage Users";

export interface UserPermissions {
  role: string;
  matrix_role: string;
  permissions: Record<ApprovalActionKey, boolean>;
  enabled_modules: Record<string, boolean>;
  can_reveal_bank?: boolean;
}

export interface TenantMember {
  user_id: number;
  email: string;
  full_name: string;
  role: string;
  status: string;
  is_active: boolean;
}

export interface PendingTenantInvite {
  id: number;
  email: string;
  full_name: string;
  role: string;
  expires_at: string;
  created_at: string;
}

export interface TenantMembersList {
  members: TenantMember[];
  pending_invites: PendingTenantInvite[];
}

export interface TenantInviteCreated {
  invite_id: number;
  email: string;
  accept_url: string;
  expires_at: string;
  email_sent?: boolean;
  email_error?: string | null;
}

export interface InvitePreview {
  email: string;
  full_name: string;
  role: string;
  tenant_name: string;
  tenant_slug: string;
  expired: boolean;
  accepted: boolean;
}

export interface InviteAcceptResult {
  message: string;
  tenant_id: string;
  tenant_name: string;
  email: string;
}

export interface MasterConfirmationBankFields {
  bsb?: string;
  account_number?: string;
  account_name?: string;
  bank_name?: string;
}

export interface MasterConfirmationBillingAddress {
  street?: string;
  suburb?: string;
  postcode?: string;
  country?: string;
}

export interface MasterConfirmationEmployeeFields {
  name?: string;
  email?: string;
  whatsapp_number?: string;
  whatsapp_number_2?: string;
  viber_number?: string;
  date_of_joining?: string;
  department?: string;
  role?: string;
  location?: string;
  division?: string;
  supervisor_1?: string;
  supervisor_2?: string;
  bank?: MasterConfirmationBankFields;
}

export interface MasterConfirmationVendorFields {
  name?: string;
  contact_email?: string;
  aliases?: string[];
  abn?: string;
  payment_terms?: string;
  billing_address?: MasterConfirmationBillingAddress;
  bank?: MasterConfirmationBankFields;
}

export interface MasterConfirmationPreview {
  kind: string;
  master_id: string;
  party_name: string;
  tenant_name: string;
  expired: boolean;
  confirmed: boolean;
  fields: MasterConfirmationEmployeeFields | MasterConfirmationVendorFields;
}

export interface MasterConfirmationSaveResult {
  kind: string;
  master_id: string;
  party_name: string;
  status: string;
  confirmed_at: string;
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

export interface InstitutionSettings {
  name: string;
  country: string;
  timezone: string;
  locale: string;
  currency: string;
  tax_label: string;
  statutory_tax_rate: number | null;
  tax_id_kind: string;
  tax_id_label: string;
  bank_routing_label: string;
  field_labels: Record<string, string>;
  /** Last-resort vision soft-bundle extracted_fields key; empty skips that step. */
  custom_bundle_field_key?: string;
  /** Fully-loaded labour cost / hour in books currency (dashboard cost-saved). */
  labor_rate_per_hour?: number;
  /** True when the tenant has invoices (currency change is an accounting event). */
  has_ledger_activity?: boolean;
}

export interface OrgAiBrief {
  legal_name: string;
  abn: string;
  aliases: string[];
  default_perspective: "buyer" | "seller" | "mixed" | string;
  intake_summary: string;
  classification_hints: string;
}

export type ChartOfAccountType = "Expense" | "Asset" | "Liability" | "Revenue" | "Equity";

export interface BillProcessingTaxProvider {
  id: string;
  name: string;
  organisation_name?: string | null;
  connected: boolean;
}

export interface SubLedgerRow {
  code: string;
  name: string;
  origin?: "party" | "manual";
}

export interface ChartOfAccountRow {
  code: string;
  name: string;
  type: ChartOfAccountType;
  sub_type?: string | null;
  linked_providers?: string[];
  subLedgers?: SubLedgerRow[];
}

export interface PlatformChartOfAccountRow {
  xero_account_id: string;
  code: string;
  name: string;
  type: ChartOfAccountType;
  sub_type: string;
  can_edit?: boolean;
  can_delete?: boolean;
  can_pull?: boolean;
  linked_providers?: string[];
  subLedgers?: SubLedgerRow[];
  status?: string | null;
}

export interface ChartOfAccountsPayload {
  accounts: ChartOfAccountRow[];
  local_accounts?: ChartOfAccountRow[];
  platform_accounts?: PlatformChartOfAccountRow[];
  xero_connected?: boolean;
  source?: "none" | "xero" | string;
  provider?: BillProcessingTaxProvider | null;
}

export interface OrgTaxRateComponent {
  name: string;
  rate: number;
}

export interface OrgTaxRateRow {
  id: string;
  display_name: string;
  tax_type: string;
  components: OrgTaxRateComponent[];
  total_rate: number;
  can_delete?: boolean;
  can_edit?: boolean;
  xero_tax_type?: string | null;
  status?: string | null;
  source?: "xero" | "local";
}

export type OrgTaxRateWrite = Omit<OrgTaxRateRow, "id" | "total_rate" | "can_delete" | "source"> & {
  id?: string;
  tax_type: string;
};

export interface TaxRatesPayload {
  tax_rates: OrgTaxRateRow[];
  xero_connected?: boolean;
  source?: "none" | "xero" | string;
  provider?: BillProcessingTaxProvider | null;
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
  pending_invite_count: number;
  invoice_count: number;
  credit_balance: number;
  credits_consumed: number;
  azure_cost_usd_total: number;
  plan: string;
  country: string;
  credits_per_page: number;
}

export interface PlatformTenantDetail extends PlatformTenantSummary {
  settings_json: Record<string, unknown> | null;
  modules: PlatformTenantModule[];
  credits_per_page_override?: number | null;
  enterprise_monthly_credits?: number | null;
  billing_anchor_date?: string | null;
}

export interface CreatePlatformTenantBody {
  name: string;
  slug: string;
  country?: string;
  currency?: string;
  industry?: string;
  first_admin_email: string;
  first_admin_name: string;
}

export interface PlatformInviteAdminBody {
  email: string;
  full_name: string;
}

export interface OnboardingStatus {
  completed: boolean;
  country: string;
  industry: string | null;
  steps: string[];
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

export type MailProvider = "google" | "microsoft";

export interface ConnectedMailbox {
  id: number;
  tenant_id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  mail_provider?: MailProvider | string;
  auth_type: "application" | "delegated" | string;
  connection_status: "connected" | "disconnected" | "error" | string;
  oauth_connected_at: string | null;
  last_error: string | null;
  last_poll_at: string | null;
  document_count?: number;
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
  mail_provider?: MailProvider | null;
  available_providers?: MailProvider[];
  google_oauth_configured?: boolean;
  microsoft_oauth_configured?: boolean;
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
    matrix_document_count?: number | null;
    matrix_flagged?: number | null;
    matrix_duplicates?: number | null;
    matrix_awaiting?: number | null;
    matrix_paid_this_month?: number | null;
    approval_queue_count?: number | null;
    approval_review_count?: number | null;
    approval_processing_count?: number | null;
    approval_approved_count?: number | null;
    approval_rejected_count?: number | null;
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

export interface ProcessingOverrides {
  skip_steps: string[];
}

export interface ApprovalChainEntry {
  user_id: number;
  role: string;
  name: string;
  at: string;
}

export interface ApprovalChain {
  module?: string;
  mode?: "one_way" | "two_way" | "three_way";
  required?: number;
  approvals?: ApprovalChainEntry[];
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
  gst_rate: string | null;
  total: string | null;
  status: InvoiceStatus;
  file_hash: string | null;
  raw_file_path: string | null;
  email_sender: string | null;
  /** Permanent Team Expenses identity stamp (Employee Master email). */
  employee_email?: string | null;
  capture_source: string | null;
  connected_mailbox_id: number | null;
  storage_vendor_slug: string | null;
  account_code: string | null;
  account_name: string | null;
  route_target: string | null;
  team_expense_kind: string | null;
  linked_advance_invoice_id: number | null;
  matched_rule_ids: string[] | null;
  vendor_confidence: number | null;
  evaluation_status:
    | "auto_coded"
    | "needs_review"
    | "pending_approval"
    | "awaiting_classification"
    | "needs_rescan"
    | "pending_vendor"
    | "unmatched_expense_vendor"
    | "awaiting_po"
    | "awaiting_so"
    | "vision_vaulted"
    | "vision_header_review"
    | "line_gl_review"
    | "line_items_review"
    | null;
  /** Ingest T4: weak/unsure duplicate signals — distinct from evaluation needs_review. */
  duplicate_review_suggested?: boolean;
  validation_results: ValidationResult[] | null;
  validation_pass_rate?: number | null;
  purchase_document_type?: string | null;
  sales_document_type?: string | null;
  so_reference?: string | null;
  document_type_code?: string | null;
  document_type_confidence?: number | null;
  llm_suggested_dt?: string | null;
  llm_confidence?: number | null;
  document_type_extraction_fields?: string[] | null;
  bank_bsb?: string | null;
  bank_account?: string | null;
  bank_masked?: boolean;
  email_attachment_name?: string | null;
  billing_address?: string | null;
  email_subject?: string | null;
  document_text?: string | null;
  document_heading?: string | null;
  extracted_fields?: Record<string, unknown> | null;
  extraction_field_confidence?: Record<string, number> | null;
  created_at: string;
  has_stored_file: boolean;
  published_to_ledger?: boolean;
  current_stage?: string;
  current_stage_state?: "done" | "pending" | "fail" | "skipped";
  /** Actionable next step when the document is blocked (Upload / inbox). */
  resolution_hint?: string | null;
  issue_summary?: string | null;
  approval_board_column?: "review" | "processing" | "approved" | "rejected";
  processing_overrides?: ProcessingOverrides | null;
  gl_posting_applicable?: boolean;
  approval_chain?: ApprovalChain | null;
  tax_label?: string | null;
}

export interface LineItem {
  id: number;
  invoice_id: number;
  description: string | null;
  qty: string | null;
  unit_price: string | null;
  amount: string | null;
  tax_amount: string | null;
  sub_ledger?: string | null;
  parent_ledger?: string | null;
  effective_ledger?: string | null;
  gl_mapping_source?: string | null;
  gl_mapping_confidence?: number | null;
  gl_mapping_reason?: string | null;
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
  entry_kind?: string | null;
  payment_id?: number | null;
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
  sub_ledger?: string | null;
  parent_ledger?: string | null;
  gl_mapping_source?: string | null;
  gl_mapping_confidence?: number | null;
  gl_mapping_reason?: string | null;
}

export interface InvoiceUpdatePayload {
  vendor?: string | null;
  abn?: string | null;
  invoice_no?: string | null;
  po_reference?: string | null;
  cost_centre?: string | null;
  billing_address?: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  subtotal?: string | null;
  gst?: string | null;
  total?: string | null;
  account_code?: string | null;
  account_name?: string | null;
  email_sender?: string | null;
  line_items?: LineItemUpdatePayload[];
  processing_overrides?: ProcessingOverrides | null;
  extracted_fields?: Record<string, string> | null;
}

export interface NavBadges {
  inbox_count: number;
  pending_approval: number;
  pending_classification: number;
  team_expenses_count: number;
  business_expenses_count: number;
  sales_count: number;
  payments_queue_count: number;
  collections_queue_count: number;
  bank_feeds_unsettled_count: number;
  integrations_connected: number;
}

export interface ClassificationReviewItem {
  invoice_id: number;
  document_ref?: string | null;
  status: string;
  evaluation_status?: string | null;
  llm_suggested_dt?: string | null;
  llm_confidence?: number | null;
  policy_winner_dt?: string | null;
  document_type_code?: string | null;
  review_reasons?: string[];
  document_ai_provider?: string | null;
}

export interface AiProviderStatus {
  available: boolean;
  label: string;
  reason?: string;
}

export interface AiProvidersResponse {
  azure_di: AiProviderStatus;
  azure_foundry_vision: AiProviderStatus;
  claude_vision: AiProviderStatus;
  gemini_vision: AiProviderStatus;
}

export interface MatchAmountLineApi {
  qty: number;
  uom?: string | null;
  unit_price?: number | null;
  line_value?: number | null;
}

export interface LineMatchResultApi {
  status: string;
  description?: string | null;
  sku?: string | null;
  order_qty?: number | null;
  order_uom?: string | null;
  order_unit_price?: number | null;
  received_qty?: number | null;
  received_uom?: string | null;
  invoice_qty?: number | null;
  invoice_uom?: string | null;
  invoice_unit_price?: number | null;
  qty_variance_value?: number;
  price_variance_value?: number;
  order_line_key?: number | string | null;
  invoice_line_key?: number | string | null;
}

export interface ThreeWayMatchDisplayApi {
  base_uom?: string | null;
  po_on_document: MatchAmountLineApi;
  po_for_match: MatchAmountLineApi;
  grn_on_document?: MatchAmountLineApi | null;
  grn_for_match?: MatchAmountLineApi | null;
  invoice_on_document?: MatchAmountLineApi | null;
  invoice_for_match?: MatchAmountLineApi | null;
  match_explanation?: string | null;
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
  display?: ThreeWayMatchDisplayApi | null;
  line_results?: LineMatchResultApi[];
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
  match_summary?: {
    status: string;
    currency: string;
    po_number?: string | null;
    po_qty?: number | null;
    po_unit_price?: number | null;
    po_value: number;
    po_date?: string | null;
    grn_present?: boolean;
    grn_qty?: number | null;
    grn_date?: string | null;
    grn_receiver?: string | null;
    grn_condition?: string | null;
    invoice_no?: string | null;
    invoice_qty?: number | null;
    invoice_unit_price?: number | null;
    invoice_value?: number;
    invoice_gst?: number;
    invoice_total: number;
    qty_variance_value?: number;
    price_variance_value?: number;
    total_deviation?: number;
    deviation?: number;
  } | null;
  purchase_register?: PurchaseOrderApi | null;
}

export interface SalesDossierMember {
  role: string;
  label: string;
  invoice_id: number | null;
  document_ref: string | null;
  present: boolean;
  has_stored_file: boolean;
  is_current: boolean;
}

export interface SalesDossierResponse {
  so_reference: string | null;
  current_role: string | null;
  members: SalesDossierMember[];
  sales_order_id: number | null;
  match: ThreeWayMatchApi | null;
  match_status: string | null;
  match_summary?: PurchaseDossier["match_summary"];
  sales_register?: SalesOrderApi | null;
}

export interface SalesOrderApi {
  id: number;
  so_number: string;
  customer: string | null;
  so_date: string | null;
  item: string | null;
  requestor: string | null;
  so_qty: number;
  so_unit_price: number;
  dn_qty: number | null;
  dn_date: string | null;
  dn_shipper: string | null;
  dn_condition: string | null;
  invoice_id: number | null;
  so_document_id?: number | null;
  dn_document_id?: number | null;
  invoice_no: string | null;
  invoice_qty: number;
  invoice_unit_price: number;
  gst_rate: number;
  variance_approved: boolean;
  variance_approval_chain?: ApprovalChain | null;
  status: string;
  three_way_match_status?: "full_match" | "partial" | "mismatch" | null;
  match: ThreeWayMatchApi;
  match_mode?: string;
  route_target?: string | null;
  evaluation_status?: string | null;
  matched_rule_ids?: string[];
  matched_rule_name?: string | null;
  matched_gl?: string | null;
  ledger?: string | null;
  sub_ledger?: string | null;
  sales_rule_id?: string | null;
  currency?: string | null;
}

export interface TwoWaySalesMatchApi {
  invoice_id: number;
  dn_invoice_id: number | null;
  invoice_no: string | null;
  customer: string | null;
  dn_qty: number | null;
  invoice_qty: number;
  invoice_unit_price: number;
  gst_rate: number;
  match: ThreeWayMatchApi;
  match_mode: string;
  route_target?: string | null;
  evaluation_status?: string | null;
  document_type_code?: string | null;
}

export interface TwoWaySalesListApi {
  register_rows: SalesOrderApi[];
  orphan_rows: TwoWaySalesMatchApi[];
}

export interface CollectionApi {
  id: number;
  invoice_id: number;
  customer: string | null;
  amount: number;
  currency: string;
  status: string;
  tab: string;
  due_date: string | null;
  received_date: string | null;
  failure_reason: string | null;
}

export interface CollectionWorkspaceKpis {
  open_count: number;
  overdue_count: number;
  due_soon_count: number;
  queue_count: number;
  awaiting_count: number;
  received_count: number;
  failed_count: number;
  outstanding_by_currency: Record<string, number>;
}

export interface PaymentWorkspaceKpis {
  open_count: number;
  overdue_count: number;
  due_soon_count: number;
  queue_count: number;
  awaiting_count: number;
  scheduled_count: number;
  paid_count: number;
  failed_count: number;
  outstanding_by_currency: Record<string, number>;
}

export interface CollectionMarkReceivedPayload {
  received_date?: string;
  note?: string;
}

export interface Customer {
  id: number;
  customer_slug: string;
  customer_name: string;
  sender_pattern: string;
  abn: string | null;
  approved: boolean;
  created_at: string;
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
  variance_approval_chain?: ApprovalChain | null;
  status: string;
  three_way_match_status?: "full_match" | "partial" | "mismatch" | null;
  match: ThreeWayMatchApi;
  match_mode?: string;
  route_target?: string | null;
  evaluation_status?: string | null;
  matched_rule_ids?: string[];
  matched_rule_name?: string | null;
  matched_gl?: string | null;
  ledger?: string | null;
  sub_ledger?: string | null;
  purchase_rule_id?: string | null;
  currency?: string | null;
}

export type PaymentExecutionEligibilityStatus =
  | "not_ready"
  | "awaiting_approval"
  | "blocked_stripe_setup"
  | "blocked_vendor_payout_setup"
  | "ready_dry_run"
  | "manual_instruction_available"
  | "instruction_created"
  | "blocked_limit"
  | "blocked_tenant_disabled"
  | "scheduled"
  | "paid"
  | "failed";

export interface PaymentExecutionInstructionApi {
  id: number;
  payment_id: number;
  instruction_reference: string;
  vendor_name: string | null;
  vendor_payout_method_label: string | null;
  amount: number;
  currency: string;
  due_date: string | null;
  execution_mode: string;
  status: string;
  created_by_name: string | null;
  created_by_email: string | null;
  created_at: string;
}

export interface PaymentExecutionInstructionExportApi {
  payment_id: number;
  instruction_reference: string;
  vendor_name: string | null;
  vendor_payout_method_label: string | null;
  amount: number;
  currency: string;
  due_date: string | null;
  execution_mode: string;
  status: string;
  created_by: string | null;
  created_at: string;
  export_format: string;
  disclaimer: string;
}

export interface PaymentMarkPaidManualPayload {
  reference: string;
  paid_date: string;
  proof_reference: string;
  note?: string;
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
  vendor_payout_status: string | null;
  vendor_payout_method_type: string | null;
  execution_readiness_status: PaymentExecutionEligibilityStatus | null;
  execution_blocking_reason: string | null;
  execution_instruction: PaymentExecutionInstructionApi | null;
}

export interface PaymentExecutionReadinessResponse {
  payment_id: number;
  can_execute: boolean;
  execution_mode: "dry_run";
  blocking_reasons: string[];
  warnings: string[];
  tenant_stripe_ready: boolean;
  vendor_payout_ready: boolean;
  approval_ready: boolean;
  amount_ready: boolean;
  manual_execution_ready: boolean;
  role_ready: boolean | null;
  limit_ready: boolean;
  tenant_execution_enabled: boolean;
  recommended_action: string | null;
  payments_execution_enabled: boolean;
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
  document_ref?: string | null;
  event: string;
  detail: Record<string, unknown> | null;
  created_at: string;
  vendor: string | null;
  status: InvoiceStatus | null;
  summary?: string | null;
}

export type NotificationSeverity = "action" | "error" | "info";

export interface NotificationItem {
  id: string;
  source: "audit" | "system";
  audit_log_id: number | null;
  event: string;
  title: string;
  summary: string | null;
  severity: NotificationSeverity;
  href: string | null;
  created_at: string;
  is_unread: boolean;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  unread_count: number;
  last_read_at: string | null;
}

export interface TopVendorRow {
  vendor: string;
  amount: string | number;
  invoice_count: number;
  counterparty_label?: string;
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
  document_ref?: string | null;
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

export interface PositionLiquidityMeta {
  currency: string;
  period_label: string;
  as_of: string;
  period_start: string;
  period_end: string;
  environment_label?: string | null;
  coverage_gaps?: string[];
  notes: string[];
}

export interface PositionLiquidityKpis {
  ap_outstanding: string;
  approved_not_paid: string;
  due_next_7_days: string;
  due_next_14_days: string;
  due_next_30_days: string;
  overdue: string;
  overdue_pct: string | null;
  overdue_threshold_pct: string;
  dpo_days: string | null;
  dpo_prior_year_days: string | null;
  on_time_payment_rate_pct: string | null;
  discount_capture_rate_pct: string | null;
  budget_utilisation_pct: string | null;
  budget_actual: string;
  budget_allocated: string;
  budget_committed: string;
  advances_outstanding: string;
  advances_overdue: string;
  advances_overdue_employees: number;
  open_exceptions_count: number;
  open_exceptions_at_risk: string;
  claims_pending_count: number;
  claims_pending_value: string;
  documents_to_review_count: number;
  documents_to_review_value: string;
  documents_processing_count: number;
  documents_processing_value: string;
  payments_queue_count: number;
  payments_queue_value: string;
  vendor_top10_concentration_pct: string | null;
  vendor_non_po_spend_pct: string | null;
}

export interface PositionLiquidityDashboard {
  meta: PositionLiquidityMeta;
  kpis: PositionLiquidityKpis;
}

export interface EfficiencyAutomationMeta {
  currency: string;
  period_label: string;
  as_of: string;
  period_start: string;
  period_end: string;
  month_start: string;
  environment_label?: string | null;
  coverage_gaps?: string[];
  notes: string[];
}

export interface EfficiencyAutomationKpis {
  touchless_processing_pct: string | null;
  touchless_target_pct: string;
  first_pass_validation_pct: string | null;
  straight_through_pct: string | null;
  cost_per_invoice: string | null;
  manual_cost_per_invoice_baseline: string;
  cost_improvement_pct: string | null;
  avg_processing_minutes: string | null;
  manual_processing_minutes_baseline: string;
  hours_saved_ytd: string;
  fte_equivalent: string | null;
  fte_hours_per_year: string;
  documents_processed_ytd: number;
  documents_processed_mtd: number;
  documents_capture_email: number;
  documents_capture_upload: number;
  documents_capture_whatsapp: number;
  documents_capture_viber: number;
  vault_documents_total: number;
  duplicates_prevented_amount: string;
  duplicates_prevented_events: number;
  fraud_blocked_amount: string;
  fraud_blocked_events: number;
  discount_captured: string | null;
  discount_available: string | null;
  total_value_delivered: string | null;
  automation_savings_amount: string;
  sync_success_pct: string | null;
  sync_dead_letter_count: number;
  sync_providers_label: string;
  documents_past_retention: number;
  document_retention_days: number;
  missing_supporting_docs: number;
}

export interface EfficiencyAutomationDashboard {
  meta: EfficiencyAutomationMeta;
  kpis: EfficiencyAutomationKpis;
}

export interface CashLiabilityOutlookMeta {
  currency: string;
  as_of: string;
  period_label: string;
  period_start: string;
  period_end: string;
  horizon_weeks: number;
  environment_label?: string | null;
  coverage_gaps?: string[];
  notes: string[];
}

export interface CashOutlookWeek {
  week_start: string;
  label: string;
  confirmed_ap: string;
  probable_ap: string;
  recurring: string;
  reimbursements: string;
  advances: string;
  tax: string;
  total_outflow: string;
  available_balance: string | null;
}

export interface CashOutlookSummary {
  next_week_outflow: string;
  total_horizon_outflow: string;
  peak_week_outflow: string;
  peak_week_label: string;
  coverage_ratio: string | null;
  opening_cash_balance: string | null;
}

export interface ApAgeingBucket {
  bucket: string;
  amount: string;
}

export interface CashLiabilityOutlookDashboard {
  meta: CashLiabilityOutlookMeta;
  weeks: CashOutlookWeek[];
  summary: CashOutlookSummary;
  ap_ageing: ApAgeingBucket[];
  ap_ageing_total: string;
}

export interface BudgetConcentrationRiskMeta {
  currency: string;
  period_label: string;
  as_of: string;
  period_start: string;
  period_end: string;
  budget_group_label: string;
  environment_label?: string | null;
  coverage_gaps?: string[];
  notes: string[];
}

export interface BudgetDepartmentRow {
  name: string;
  budget: string;
  actual: string;
  committed: string;
  owner: string;
}

export interface BudgetEncumbranceSummary {
  budget: string;
  actual: string;
  committed: string;
  remaining: string;
  utilisation_pct: string | null;
}

export interface VendorConcentrationRow {
  name: string;
  spend: string;
  invoice_count: number;
  cycle_days: string | null;
  po_backed_pct: string | null;
  risk_level: string;
  bank_change_flag: boolean;
}

export interface VendorConcentrationSummary {
  top10_concentration_pct: string | null;
  non_po_spend_pct: string | null;
  contracted_in_top10: number;
  high_risk_count: number;
}

export interface BudgetConcentrationRiskDashboard {
  meta: BudgetConcentrationRiskMeta;
  departments: BudgetDepartmentRow[];
  budget_summary: BudgetEncumbranceSummary;
  vendors: VendorConcentrationRow[];
  vendor_summary: VendorConcentrationSummary;
}

export interface CfoAlertRow {
  severity: "high" | "med" | "low";
  title: string;
  detail: string;
  meta: string;
  module: string;
  source: string;
}

export interface CfoAlertsSummary {
  active_count: number;
  high_count: number;
  med_count: number;
  low_count: number;
}

export interface CfoAlertsMeta {
  currency: string;
  period_label: string;
  as_of: string;
  period_start: string;
  period_end: string;
  environment_label?: string | null;
  coverage_gaps?: string[];
  notes: string[];
}

export interface CfoAlertsDashboard {
  meta: CfoAlertsMeta;
  summary: CfoAlertsSummary;
  alerts: CfoAlertRow[];
}

export interface ProcessEfficiencyTrendPoint {
  label: string;
  period_start: string;
  period_end: string;
  dpo_days: string | null;
  stp_pct: string | null;
}

export interface ProcessEfficiencyTrendsSummary {
  stp_target_pct: string;
  latest_dpo_days: string | null;
  latest_stp_pct: string | null;
  months_with_dpo: number;
  months_with_stp: number;
}

export interface ProcessEfficiencyTrendsMeta {
  currency: string;
  period_label: string;
  as_of: string;
  window_start: string;
  window_end: string;
  environment_label?: string | null;
  coverage_gaps?: string[];
  notes: string[];
}

export interface ProcessEfficiencyTrendsDashboard {
  meta: ProcessEfficiencyTrendsMeta;
  points: ProcessEfficiencyTrendPoint[];
  summary: ProcessEfficiencyTrendsSummary;
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
  executive_kpis?: ExecutiveKpis;
  capture_sources?: CaptureSourceApiRow[];
  risk_compliance?: RiskComplianceApiRow[];
  attention?: AttentionPanelApi | null;
  operations?: OperationsPanelApi;
  extraction_quality?: ExtractionQualityPointApi[];
  approval_queue?: ApprovalQueueStatsApi;
  user_layer?: UserLayerMetricApi[];
}

export interface ExecutiveKpiDelta {
  direction: "up" | "down" | "flat";
  text: string;
  favorable: boolean | null;
}

export interface ExecutiveKpis {
  documents_processed: number;
  documents_delta: ExecutiveKpiDelta | null;
  time_saved_minutes: number;
  time_saved_hours_label: string;
  avg_time_saved_per_doc_minutes: number;
  automation_efficiency_pct: number;
  automation_delta: ExecutiveKpiDelta | null;
  cost_saved: number;
}

export interface CaptureSourceApiRow {
  id: "email" | "whatsapp" | "viber" | "upload";
  label: string;
  document_count: number;
  avg_time_saved_minutes: number;
  time_saved_minutes: number;
  manual_minutes: number;
  cost_saved: number;
  href: string;
}

export interface RiskComplianceApiRow {
  id: string;
  label: string;
  count: number;
  href: string;
  badge: string;
}

export interface AttentionPriorityApi {
  title: string;
  body: string;
  cta_label: string;
  cta_href: string;
}

export interface AttentionMetricApi {
  label: string;
  value: string;
  delta_text: string;
  delta_down?: boolean;
  delta_good: boolean;
  bars: number[];
}

export interface AttentionPanelApi {
  priority: AttentionPriorityApi;
  processed: AttentionMetricApi;
  turnaround: AttentionMetricApi;
}

export interface OpsStatusCountsApi {
  processed: number;
  posted: number;
  rejected: number;
  review_pending: number;
  approvals_pending: number;
}

export interface OpsDocTypeRowApi {
  id: string;
  label: string;
  counts: OpsStatusCountsApi;
}

export interface OpsMemberSnapshotApi {
  id: string;
  label: string;
  documents_processed: number;
  time_saved_minutes: number;
  automation_rate_pct: number;
  pending_actions: number;
  accuracy_pct: number;
  by_doc_type: OpsDocTypeRowApi[];
}

export interface OperationsPanelApi {
  windows: Record<string, OpsMemberSnapshotApi[]>;
}

export interface ExtractionQualityPointApi {
  metric: string;
  accuracy: number;
}

export interface ApprovalQueueStatsApi {
  pending: number;
  value_label: string;
  median_time_label: string;
}

export interface UserLayerStagesApi {
  document_fetched: number;
  pending_confirmation: number;
  pending_approval: number;
  pending_posting: number;
  pending_payment: number;
}

export interface UserLayerMetricApi {
  id: string;
  label: string;
  stages: UserLayerStagesApi;
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

export type ReportCategory =
  | "payables_receivables"
  | "budgets_performance"
  | "transactions"
  | "exceptions_controls";

export type ReportRangeKey = "month" | "quarter" | "custom";
export type ReportExportFormat = "pdf" | "xlsx";

export interface ReportCatalogItem {
  id: string;
  name: string;
  description: string;
  category: ReportCategory;
  supports_compare: boolean;
}

export interface ReportCatalogResponse {
  reports: ReportCatalogItem[];
  favourite_ids: string[];
}

export interface ReportPreviewRow {
  cells: string[];
  emphasize?: boolean;
}

export interface ReportPreview {
  report_id: string;
  title: string;
  period_label: string;
  currency: string;
  columns: string[];
  rows: ReportPreviewRow[];
  compare_columns?: string[] | null;
  empty: boolean;
  notes?: string | null;
}

export interface ReportExportRequest {
  format: ReportExportFormat;
  range: ReportRangeKey;
  compare?: boolean;
  from?: string;
  to?: string;
  layout_id?: number | null;
}

export interface ReportColumnConfig {
  columns: string[];
}

export interface ReportColumnLayoutItem {
  id: number;
  report_id: string;
  name: string;
  column_config: ReportColumnConfig;
  is_default: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ReportColumnLayoutCreate {
  name: string;
  column_config: ReportColumnConfig;
  is_default?: boolean;
}

export interface ReportColumnLayoutUpdate {
  name?: string;
  column_config?: ReportColumnConfig;
}

export interface EmployeeAdvanceSettlementRow {
  employee_id: string;
  name: string;
  role: string;
  email: string;
  whatsapp_number: string;
  whatsapp_number_2: string;
  viber_number: string | null;
  date_of_joining: string;
  department: string;
  location: string;
  division: string;
  supervisor_1: string;
  supervisor_2: string;
  bank_name: string;
  bank_account_name: string;
  bank_account_number: string;
  bank_bsb: string;
  bank_swift: string;
  bank_iban: string;
  advance_parent_ledger: string;
  advance_sub_ledger: string;
  status: string;
  claim_count: number;
  last_claim: string;
  claim_ytd_spent: number;
  advance_taken?: number | string;
  advance_used?: number | string;
  advance_ledger_balance: number | string;
  pending_against_advance: number | string;
  available_advance: number | string;
}

export interface EmployeeBudgetUtilizationRow {
  employee_id: string;
  name: string;
  role: string;
  email: string;
  whatsapp_number: string;
  whatsapp_number_2: string;
  viber_number: string | null;
  date_of_joining: string;
  department: string;
  location: string;
  division: string;
  supervisor_1: string;
  supervisor_2: string;
  bank_name: string;
  bank_account_name: string;
  bank_account_number: string;
  bank_bsb: string;
  bank_swift: string;
  bank_iban: string;
  status: string;
  budget_monthly: number;
  budget_quarterly: number;
  budget_annual: number;
  category_caps: string;
  mtd_spent: number;
  qtd_spent: number;
  ytd_spent: number;
  claim_count: number;
  last_claim: string;
  monthly_remaining: number | null;
  quarterly_remaining: number | null;
  annual_remaining: number | null;
  monthly_utilization_pct: number | null;
  quarterly_utilization_pct: number | null;
  annual_utilization_pct: number | null;
  /** Outstanding Staff Advance ledger balance (cash float). */
  advance_float?: number;
  monthly_cash_committed?: number;
  quarterly_cash_committed?: number;
  annual_cash_committed?: number;
  monthly_cash_remaining?: number | null;
  quarterly_cash_remaining?: number | null;
  annual_cash_remaining?: number | null;
  monthly_cash_utilization_pct?: number | null;
  quarterly_cash_utilization_pct?: number | null;
  annual_cash_utilization_pct?: number | null;
}

export interface DepartmentBudgetRow {
  id: number;
  department: string;
  gl_ledger: string;
  period_kind: "monthly" | "quarterly" | "annual";
  period_key: string;
  allocated: number | string;
  enforcement?: "soft" | "hard";
  notes: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DepartmentBudgetUtilizationRow {
  department?: string;
  gl_ledger: string;
  period_kind: "monthly" | "quarterly" | "annual";
  period_key: string;
  allocated: number;
  consumed: number;
  remaining: number | null;
  utilization_pct: number | null;
  notes: string | null;
  enforcement?: "soft" | "hard";
  budget_id: number;
  sub_breakdown?: Array<{
    gl_ledger: string;
    consumed: number;
    pct_of_budget: number;
  }>;
  /** @deprecated Advance float is not part of GL budget tracking. */
  advance_float?: number;
  cash_committed?: number;
  cash_remaining?: number | null;
  cash_utilization_pct?: number | null;
}

export interface TeamExpenseWorkspaceKpis {
  kind_counts: Record<string, number>;
  open_count: number;
  pending_count: number;
  posted_count: number;
  posted_by_currency: Record<string, number>;
}

export interface PurchaseWorkspaceKpis {
  awaiting_po_count: number;
  needs_action_count: number;
}

export interface SalesWorkspaceKpis {
  awaiting_so_count: number;
  needs_action_count: number;
}

export interface EmployeeExpenseSummaryRow {
  employee_id: string;
  employee_name: string;
  role: string;
  employee_email: string;
  mobile: string;
  department: string;
  division: string;
  location: string;
  document_no: string;
  invoice_date: string | null;
  team_expense_kind: string;
  document_type_code: string;
  line_description: string;
  line_qty: number | string | null;
  line_amount: number | string | null;
  ledger_code: string;
  main_gl: string;
  sub_ledger: string;
  status: string;
  evaluation_status: string;
  invoice_id: number;
  currency: string;
}

export interface EmployeeSpendDetailRow {
  employee_id: string;
  name: string;
  role: string;
  email: string;
  whatsapp_number: string;
  whatsapp_number_2: string;
  viber_number: string | null;
  date_of_joining: string;
  department: string;
  location: string;
  division: string;
  supervisor_1: string;
  supervisor_2: string;
  bank_name: string;
  bank_account_name: string;
  bank_account_number: string;
  bank_bsb: string;
  bank_swift: string;
  bank_iban: string;
  advance_parent_ledger: string;
  advance_sub_ledger: string;
  status: string;
  main_gl: string;
  sub_ledger: string;
  sub_gl_budget: number;
  employee_spend_ytd: number;
  pct_of_sub_gl_used: number | null;
  claim_count: number;
  advance_pending: number | string;
  cash_reimbursed_ytd: number;
  last_claim_date: string;
  budget_monthly: number;
  budget_quarterly: number;
  budget_annual: number;
  mtd_spent: number;
  qtd_spent: number;
  ytd_spent_total: number;
  monthly_remaining: number | null;
  quarterly_remaining: number | null;
  annual_remaining: number | null;
  monthly_utilization_pct: number | null;
  quarterly_utilization_pct: number | null;
  annual_utilization_pct: number | null;
}

export interface EmployeeAdvanceDetailRow {
  employee_id: string;
  name: string;
  role: string;
  email: string;
  whatsapp_number: string;
  whatsapp_number_2: string;
  viber_number: string | null;
  date_of_joining: string;
  department: string;
  location: string;
  division: string;
  supervisor_1: string;
  supervisor_2: string;
  bank_name: string;
  bank_account_name: string;
  bank_account_number: string;
  bank_bsb: string;
  bank_swift: string;
  bank_iban: string;
  advance_parent_ledger: string;
  advance_sub_ledger: string;
  status: string;
  movement_type: string;
  document_no: string;
  document_date: string | null;
  took: number | string;
  used: number | string;
  outstanding_after: number | string;
  pending_claims: number | string;
  available: number | string;
  cash_reimbursed: number | string;
  document_status: string;
  approved_by: string;
  approved_on: string;
  invoice_id: number;
}

export interface SubledgerBalanceRow {
  registry_id: number;
  slug: string;
  name: string;
  abn: string | null;
  approved: boolean;
  balance: number | string;
  document_count: number;
  last_activity_date: string | null;
}

export interface SubledgerUnregisteredBucket {
  balance: number | string;
  document_count: number;
}

export interface SubledgerTotals {
  balance: number | string;
  counterparty_count: number;
}

export interface SubledgerBalancesResponse {
  base_currency: string;
  as_of: string;
  control_account_code: string;
  control_account_name: string;
  rows: SubledgerBalanceRow[];
  unregistered: SubledgerUnregisteredBucket;
  totals: SubledgerTotals;
}

export interface Vendor {
  id: number;
  vendor_slug: string;
  vendor_name: string;
  sender_pattern: string;
  abn: string | null;
  approved: boolean;
}

export interface VendorActivity {
  vendor: string;
  invoice_count: number;
  by_currency: Record<string, number>;
  email: string | null;
  default_account: string | null;
  net_days: number | null;
}

export type VendorPayoutMethodType =
  | "manual_bank"
  | "stripe_connected_account"
  | "external_bank_phase2"
  | "paypal"
  | "stripe_global_payouts"
  | "stripe_treasury"
  | "external_ap_provider";

export type VendorPayoutMethodStatus =
  | "not_configured"
  | "pending"
  | "verified"
  | "failed"
  | "disabled";

export interface VendorPayoutMethod {
  id: number;
  vendor_id: number;
  method_type: VendorPayoutMethodType | string;
  display_label: string | null;
  stripe_account_id: string | null;
  last4: string | null;
  currency: string;
  status: VendorPayoutMethodStatus | string;
  is_default: boolean;
  provider?: string | null;
  provider_recipient_id?: string | null;
  recipient_status?: string | null;
  recipient_country?: string | null;
  recipient_currency?: string | null;
  created_at: string;
  updated_at: string;
}

export interface VendorPayoutMethodCreate {
  method_type: VendorPayoutMethodType;
  display_label?: string | null;
  stripe_account_id?: string | null;
  last4?: string | null;
  currency?: string;
  status?: VendorPayoutMethodStatus;
  is_default?: boolean;
}

export interface VendorPayoutMethodUpdate {
  method_type?: VendorPayoutMethodType;
  display_label?: string | null;
  stripe_account_id?: string | null;
  last4?: string | null;
  currency?: string;
  status?: VendorPayoutMethodStatus;
  is_default?: boolean;
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
  gemini_vision_available: boolean;
  azure_foundry_vision_available: boolean;
  claude_vision_available: boolean;
  default_document_ai_provider: string;
  azure_postgres_enabled: boolean;
  azure_redis_enabled: boolean;
  appinsights_enabled: boolean;
  azure_location: string;
  azure_webapp_url: string;
  abn_validation_mode: string;
  rule_book_config_path: string;
  cors_origins: string;
  whatsapp_configured: boolean;
  app_env: string;
  payment_environment_label: string;
  public_app_base_url?: string;
  public_api_base_url?: string;
  stripe_mode: string;
  xero_configured: boolean;
  quickbooks_configured: boolean;
  stripe_global_payouts_enabled?: boolean;
  stripe_global_payouts_access_status: string;
  stripe_payments_execution_enabled: boolean;
  stripe_live_payments_enabled: boolean;
  payment_manual_execution_enabled: boolean;
  payment_manual_execution_limit_usd: number;
  payment_execution_disabled: boolean;
  use_field_registry?: boolean;
}

export interface RegistryFieldOption {
  key: string;
  label: string;
  data_type?: string;
  category?: string;
  posting_critical?: boolean;
  grounding_required?: boolean;
  synonyms?: string[];
}

export interface RegistryFieldsResponse {
  version: string;
  use_field_registry: boolean;
  fields: RegistryFieldOption[];
}

export interface AccountingIntegrationItem {
  provider: string;
  configured: boolean;
  status: string;
  display_name: string | null;
  provider_tenant_id: string | null;
  scopes: string | null;
  connected_at: string | null;
  last_error: string | null;
}

export interface AccountingIntegrationsStatus {
  xero: AccountingIntegrationItem;
  quickbooks_online: AccountingIntegrationItem;
}

export interface StripeGlobalPayoutsReadinessResponse {
  enabled: boolean;
  access_status: string;
  financial_account_configured: boolean;
  supported_countries: string[];
  supported_currencies: string[];
  max_amount_usd: number;
  ready: boolean;
  blocking_reason: string | null;
  recommended_action: string | null;
  environment: string;
  stripe_mode: string;
  live_execution_enabled: boolean;
}

export interface AccountingIntegrationItem {
  provider: string;
  configured: boolean;
  status: string;
  display_name: string | null;
  provider_tenant_id: string | null;
  scopes: string | null;
  connected_at: string | null;
  last_error: string | null;
}

export interface AccountingIntegrationsStatus {
  xero: AccountingIntegrationItem;
  quickbooks_online: AccountingIntegrationItem;
}

export type XeroIntegrationStatus =
  | "disconnected"
  | "connected"
  | "expired"
  | "error"
  | "needs_reauth"
  | "organisation_selection_required";

export interface XeroReadiness {
  enabled?: boolean;
  configured: boolean;
  connected: boolean;
  ready: boolean;
  status: XeroIntegrationStatus | string;
  organisation_selected: boolean;
  organisation_selection_required?: boolean;
  provider_tenant_id: string | null;
  display_name: string | null;
  connection_count: number;
  last_error: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  needs_reauth?: boolean;
  last_successful_sync_at?: string | null;
  connection_verified?: boolean;
  verified_at?: string | null;
  latest_sync_job_status?: string | null;
  latest_sync_job_type?: string | null;
}

export interface XeroVerifyResult {
  connected: boolean;
  needs_reauth: boolean;
  organisation_id: string | null;
  organisation_name: string | null;
  verified_at: string | null;
  message: string | null;
}

export interface XeroConnectionItem {
  id: number;
  xero_connection_id: string;
  xero_tenant_id: string;
  xero_tenant_type: string | null;
  xero_tenant_name: string | null;
  selected: boolean;
}

export interface XeroConnectionsResponse {
  connections: XeroConnectionItem[];
}

export interface XeroSelectConnectionResult {
  status: string;
  display_name: string | null;
  provider_tenant_id: string | null;
}

export interface XeroEntitySyncCounts {
  fetched: number;
  created: number;
  updated: number;
  unchanged: number;
  deactivated: number;
  failed: number;
  persisted_total: number;
}

export interface XeroSyncSettingsResult {
  organisation: XeroEntitySyncCounts;
  accounts: XeroEntitySyncCounts;
  tax_rates: XeroEntitySyncCounts;
  currencies: XeroEntitySyncCounts;
  organisation_count: number;
  account: number;
  tax_rate: number;
  currency: number;
  committed: boolean;
  job_id: number | null;
}

export interface XeroSyncContactsResult {
  contacts: XeroEntitySyncCounts;
  contact: number;
  committed: boolean;
  job_id: number | null;
}

export interface XeroMasterListMeta {
  total: number;
  limit: number;
  offset: number;
}

export interface XeroAccountRow {
  id: number;
  xero_account_id: string;
  xero_tenant_id: string;
  code: string | null;
  name: string | null;
  account_type: string | null;
  status: string | null;
  sync_status: string;
  last_synced_at: string | null;
  created_at: string | null;
  source_system: string;
  source_label: string;
  external_id: string | null;
  imported_at: string | null;
}

export interface XeroTaxRateRow {
  id: number;
  tax_type: string;
  xero_tenant_id: string;
  name: string | null;
  status: string | null;
  effective_rate: number | null;
  sync_status: string;
  last_synced_at: string | null;
  created_at: string | null;
  source_system: string;
  source_label: string;
  external_id: string | null;
  imported_at: string | null;
}

export interface XeroContactRow {
  id: number;
  xero_contact_id: string;
  xero_tenant_id: string;
  name: string | null;
  email_address: string | null;
  is_supplier: boolean;
  is_customer: boolean;
  mapping_status: string;
  sync_status: string;
  last_synced_at: string | null;
  created_at: string | null;
  source_system: string;
  source_label: string;
  external_id: string | null;
  imported_at: string | null;
}

export interface XeroSyncHistoryRow {
  id: number;
  job_type: string;
  direction: string | null;
  status: string;
  trigger_type: string | null;
  records_fetched: number;
  records_created: number;
  records_updated: number;
  records_unchanged: number;
  records_failed: number;
  records_persisted: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string | null;
}

export interface XeroExportHistoryRow {
  id: number;
  invoice_id: number | null;
  external_entity_id: string | null;
  external_number: string | null;
  external_status: string | null;
  sync_direction: string | null;
  sync_status: string | null;
  reconciliation_status: string | null;
  last_pushed_at: string | null;
  last_reconciled_at: string | null;
  amount_due: number | null;
  amount_paid: number | null;
  is_fully_paid: boolean | null;
  sync_error_message: string | null;
}

export interface XeroMasterTotals {
  accounts: number;
  tax_rates: number;
  contacts: number;
  currencies: number;
}

export interface XeroExportLedgerRow {
  sync_id: number;
  source_invoice_id: number;
  qll_transaction_id: string;
  status: string;
  external_id: string | null;
  external_number: string | null;
  external_status: string | null;
  external_total: number | null;
  attachment_status: string | null;
  attempt_count: number;
  error_bucket: string | null;
  error_code: string | null;
  error_message: string | null;
  export_complete?: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface XeroExportQueueItem {
  invoice_id: number;
  invoice_no: string | null;
  vendor: string | null;
  total: number | null;
  currency: string | null;
  valid: boolean;
  blocking_errors: Array<{ field: string; code: string; message: string }>;
}

export interface XeroPushResult {
  invoice_id: number;
  skipped: boolean;
  reason: string | null;
  external_entity_id: string | null;
  external_number: string | null;
  external_status: string | null;
  xero_type: string | null;
  synced?: boolean;
  committed?: boolean;
  last_pushed_at?: string | null;
}

export interface XeroInvoiceStatus {
  invoice_id: number;
  pushed: boolean;
  external_entity_id: string | null;
  external_number: string | null;
  external_status: string | null;
  last_pushed_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  payload_hash: string | null;
  sync_status?: string | null;
  reconciliation_status?: string | null;
  last_reconciled_at?: string | null;
  amount_due?: number | null;
  amount_paid?: number | null;
  is_fully_paid?: boolean | null;
}

export interface StripeGlobalPayoutsReadinessResponse {
  enabled: boolean;
  access_status: string;
  financial_account_configured: boolean;
  supported_countries: string[];
  supported_currencies: string[];
  max_amount_usd: number;
  ready: boolean;
  blocking_reason: string | null;
  recommended_action: string | null;
  environment: string;
  stripe_mode: string;
  live_execution_enabled: boolean;
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

export interface ViberConnection {
  id: number;
  tenant_id: string;
  bot_id: string;
  connection_status: string;
  integration_health: string;
  created_at: string;
}

export interface ViberStatus {
  configured: boolean;
  webhook_callback_url: string;
  webhook_reachable: boolean;
  webhook_reachability_hint?: string | null;
  connections: ViberConnection[];
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

/** Tenant's own bank account used to originate batch payment files (e.g. AU ABA). */
export interface RemitterBankAccount {
  bank_name: string;
  account_name: string;
  routing_code: string;
  account_number: string;
  remittance_display_name: string;
}

/** Per-tenant config for generating batch bank payment files from Scheduled payments. */
export interface BankFileSettings {
  format: string;
  remitter: RemitterBankAccount;
  aba_user_id_number: string;
  aba_financial_institution_code: string;
  aba_description: string;
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
    requires_employee_sender?: boolean | null;
    matched_count?: number;
    last_matched?: string;
  }>;
  email_capture_ingest_stats?: Record<
    string,
    { matched_count: number; last_matched: string }
  >;
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
      receivable_account?: string;
    };
    matched_count: number;
  }>;
  sales_rules: Array<{
    id: string;
    name: string;
    enabled: boolean;
    priority?: number;
    match_on: Record<string, unknown>;
    post_to: {
      ledger: string;
      sub_ledger: string;
      tax_account?: string;
      receivable_account?: string;
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
  bank_narration_rules?: Array<{
    id: string;
    name: string;
    enabled: boolean;
    priority?: number;
    match_on: Record<string, unknown>;
    post_to: { ledger: string; sub_ledger: string };
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
    receivable_account?: string;
    fallback_account: string;
  };
  team_expense_posting?: {
    default_advance_parent_ledger: string;
    settlement_account: string;
  };
  bank_file_settings?: BankFileSettings;
  document_sets: Array<{
    id: string;
    pattern: string;
    set_name: string;
    isolated?: boolean;
  }>;
  purchase_match?: {
    qty_tolerance_pct?: number;
  };
  document_classification?: {
    unclassified_document_type_code: string;
    unclassified_min_confidence: number;
  };
  org_context?: {
    legal_name: string;
    abn: string;
    aliases: string[];
    default_perspective: string;
    intake_summary?: string;
    classification_hints?: string;
  };
  ai_classification?: {
    document_ai_provider?: "azure_di" | "azure_foundry_vision" | "gemini_vision" | "claude_vision";
    auto_route_min_confidence?: number;
    llm_min_confidence?: number;
    policy_min_confidence?: number;
  };
  document_types: Array<{
    code: string;
    title: string;
    short_title: string;
    klass: string;
    posting: string;
    recognition_mode?: "signals" | "prompt";
    recognition_signals?: string[];
    llm_prompt?: string;
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
    sales_bundle_role?: string;
    team_expense_kind?: string;
    budget_control?: boolean;
    advance_control?: boolean;
    matrix_template_code?: string;
    sample_analysis?: {
      analyzed_at?: string;
      filenames?: string[];
      file_count?: number;
      applied_at?: string;
      recognition_signals?: string[];
    };
    post_to?: {
      ledger: string;
      sub_ledger: string;
      tax_account?: string;
      payable_account?: string;
      receivable_account?: string;
    };
  }>;
}

export type RuleBookRulesPayload = Omit<
  RuleBookConfig,
  "vendor_masters" | "employee_masters" | "email_capture_rules"
>;

export interface DocumentTypeRecognitionTestRequest {
  draft_document_type: Record<string, unknown>;
  document_text?: string;
  document_heading?: string;
  email_sender?: string;
  attachment_name?: string;
}

export interface DocumentTypeRecognitionTestResponse {
  matches: boolean;
  match_rules_passed: boolean;
  exclude_rules_passed: boolean;
  summary: string;
  classifier_enabled: boolean;
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
  currency?: string;
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
  has_mixed_currencies?: boolean;
  currencies?: string[];
  totals_by_currency?: Record<string, string | number>;
  dr_by_currency?: Record<string, string | number>;
  cr_by_currency?: Record<string, string | number>;
  journal_lines: ReconciliationJournalLine[];
  invoices: Array<{
    id: number;
    vendor: string | null;
    invoice_no: string | null;
    total: string | null;
    currency?: string;
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
  currency?: string;
  postings: ReconPostingRow[];
}

export interface ReconDayOverviewRow {
  date: string;
  count: number;
  sum_dr: string | number;
  sum_cr: string | number;
  delta: string | number;
  has_mixed_currencies?: boolean;
  currencies?: string[];
  totals_by_currency?: Record<string, string | number>;
  dr_by_currency?: Record<string, string | number>;
  cr_by_currency?: Record<string, string | number>;
  invoices: ReconInvoiceOverviewRow[];
}

export interface ReconciliationOverview {
  sum_totals: string | number;
  sum_dr: string | number;
  sum_cr: string | number;
  delta_dr_cr: string | number;
  balanced: boolean;
  base_currency: string;
  has_mixed_currencies?: boolean;
  totals_by_currency?: Record<string, string | number>;
  dr_by_currency?: Record<string, string | number>;
  cr_by_currency?: Record<string, string | number>;
  by_date: ReconDayOverviewRow[];
  document_count?: number;
  total_day_count?: number;
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
  document_ref?: string | null;
  invoice_no?: string | null;
  invoice_date?: string | null;
  total?: string | number | null;
  currency?: string;
  capture_source?: string | null;
  document_heading?: string | null;
  document_type_code?: string | null;
}

export interface VaultTreeResponse {
  tree: VaultTreeNode[];
  files: VaultApiFile[];
  blob_enabled: boolean;
  file_count?: number;
}

export interface VaultFilesResponse {
  files: VaultApiFile[];
  count: number;
}

export interface VaultDocumentSetInvoice {
  id: number;
  vendor?: string | null;
  invoice_no?: string | null;
  invoice_date?: string | null;
  document_ref?: string | null;
  total?: string | number | null;
  currency?: string;
  capture_source?: string | null;
  document_heading?: string | null;
  document_type_code?: string | null;
  purchase_document_type?: string | null;
}

export interface VaultDocumentSetCard {
  id: string;
  pattern: string;
  set_name: string;
  isolated?: boolean;
  match_count: number;
  invoices: VaultDocumentSetInvoice[];
}

export interface VaultDocumentSetsResponse {
  sets: VaultDocumentSetCard[];
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
  approval_matrix?: {
    by_module: Record<string, "one_way" | "two_way" | "three_way">;
  };
}

export type MatrixCellState = "done" | "pending" | "fail" | "skipped";

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
  paid_date?: string | null;
  conflict_with?: string | null;
  conflict_detail?: MatrixConflictRow[] | null;
  line_item_count?: number;
  advance_auth?: string;
  budget_auth?: string;
  acc_sync?: string;
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
  currency?: string;
}

export interface LedgerExportGroupMeta {
  count: number;
  totals_by_currency: Record<string, number>;
}

export interface LedgerLinkExports {
  invoices: LedgerExportRow[];
  bills: LedgerExportRow[];
  expenses: LedgerExportRow[];
  purchases: LedgerExportRow[];
  payments: LedgerExportRow[];
  group_meta?: Record<string, LedgerExportGroupMeta>;
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
  currency?: string;
  last_top_up: string;
  transactions: WalletTransaction[];
}

export interface StripeAccount {
  id: number;
  tenant_id: string;
  stripe_account_id: string;
  account_type: string | null;
  charges_enabled: boolean;
  payouts_enabled: boolean;
  details_submitted: boolean;
  onboarding_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface StripeConnectResponse {
  account: StripeAccount;
  onboarding_url: string | null;
}

export interface StripeOnboardingLinkResponse {
  url: string;
}

export interface StripeOAuthUrlResponse {
  url: string;
}

export interface StripeDisconnectResponse {
  disconnected: boolean;
}

export interface StripeReadinessResponse {
  connected: boolean;
  account_id: string | null;
  onboarding_status: string | null;
  charges_enabled: boolean;
  payouts_enabled: boolean;
  ready_for_charges: boolean;
  ready_for_payouts: boolean;
  blocking_reason: string | null;
  recommended_action: string | null;
}

export interface StripeBalanceAmount {
  amount: number | null;
  currency: string | null;
}

export interface StripeBalanceResponse {
  available: StripeBalanceAmount[];
  pending: StripeBalanceAmount[];
  livemode: boolean;
  snapshot_id: number;
}

export interface StripeTransaction {
  id: number;
  stripe_transaction_id: string;
  type: string | null;
  amount: number | null;
  currency: string | null;
  status: string | null;
  description: string | null;
  available_on: string | null;
}

export interface PaypalReadinessError {
  code: string | null;
  message: string | null;
}

export interface PaypalReadinessResponse {
  configured: boolean;
  connected: boolean;
  merchant_id: string | null;
  display_name: string | null;
  onboarding_complete: boolean;
  payments_enabled: boolean;
  payouts_enabled: boolean;
  balance_available: boolean;
  transactions_available: boolean;
  needs_reauthorization: boolean;
  last_verified_at: string | null;
  last_error: PaypalReadinessError | string | null;
}

export interface PaypalConnectResponse {
  mode: string;
  action?: string | null;
  merchant_id?: string | null;
  onboarding_url?: string | null;
  redirect_url?: string | null;
  tracking_id?: string | null;
  state?: string | null;
  readiness?: PaypalReadinessResponse | null;
}

export interface PaypalDisconnectResponse {
  configured: boolean;
  connected: boolean;
  merchant_id: string | null;
  display_name: string | null;
  onboarding_complete: boolean;
  payments_enabled: boolean;
  payouts_enabled: boolean;
  balance_available: boolean;
  transactions_available: boolean;
  needs_reauthorization: boolean;
  last_verified_at: string | null;
  last_error: PaypalReadinessError | string | null;
}

export interface PaypalBalanceRow {
  currency: string | null;
  total?: string | number | null;
  available?: string | number | null;
  primary?: boolean;
}

export interface PaypalBalanceResponse {
  available: boolean;
  reason?: string | null;
  balances: PaypalBalanceRow[];
  merchant_id?: string | null;
  as_of?: string | null;
}

export interface PaypalTransaction {
  id: number;
  provider: string;
  provider_account_id: string | null;
  provider_transaction_id: string | null;
  transaction_type: string | null;
  status: string | null;
  currency: string | null;
  gross_amount: string | number | null;
  fee_amount: string | number | null;
  net_amount: string | number | null;
  recipient: string | null;
  occurred_at: string | null;
  last_synced_at: string | null;
}

export interface PaypalTransactionsResponse {
  available: boolean;
  reason?: string | null;
  transactions: PaypalTransaction[];
  page?: number;
  page_size?: number;
  merchant_id?: string | null;
}

export interface PaypalPayoutRequest {
  payable_id: number;
  recipient_method_id: number;
  amount?: string | null;
  currency?: string | null;
  note?: string | null;
}

export interface PaypalPayoutAttempt {
  id: number;
  payment_id: number;
  provider: string;
  provider_batch_id: string | null;
  provider_item_id: string | null;
  provider_transaction_id: string | null;
  provider_request_id: string | null;
  provider_status: string | null;
  recipient_type: string | null;
  recipient_value: string | null;
  amount: string | null;
  currency: string | null;
  status: string;
  failure_code: string | null;
  failure_message: string | null;
  submitted_at: string | null;
  completed_at: string | null;
  last_checked_at: string | null;
  created_at: string | null;
}

export interface PlanInfo {
  plan: string;
  region: string;
  currency_code: string;
  monthly_credits: number;
  max_users: number;
  social_integration: boolean;
  email_integration: boolean;
  studio_monthly_price: number;
  credits_per_page: number;
  topup_factor: number;
}

export interface CreditLedgerEntry {
  id: number;
  event_type: string;
  description: string;
  pages?: number | null;
  credits_per_page?: number | null;
  credits_delta: number;
  balance_after: number;
  plan_at_event?: string | null;
  amount_paid?: number | null;
  currency_code?: string | null;
  azure_cost_usd?: number | null;
  azure_cost_breakdown?: Record<string, unknown> | null;
  filename?: string | null;
  invoice_id?: number | null;
  stripe_hosted_invoice_url?: string | null;
  stripe_receipt_url?: string | null;
  created_at?: string | null;
}

export type BillingLedgerCategory = "usage" | "invoice";

export interface BillingState {
  balance: number;
  plan: string;
  credits_per_page: number;
  credits_consumed: number;
  plan_info: PlanInfo;
  billing_anchor_date?: string | null;
  fy_days_remaining?: number | null;
  can_upgrade_studio: boolean;
  can_top_up: boolean;
  is_enterprise: boolean;
  platform_billing_enabled?: boolean;
  subscription_status?: string | null;
}

export interface CheckoutSessionResult {
  checkout_url?: string | null;
  session_id?: string | null;
  status: string;
  pending_signup_id?: string | null;
  tenant_id?: string | null;
  completed_without_checkout?: boolean;
  access_token?: string | null;
  refresh_token?: string | null;
  user?: AuthUser | null;
}

export interface CheckoutStatusResult {
  session_id: string;
  status?: string | null;
  payment_status?: string | null;
  mode?: string | null;
  event_type?: string | null;
  tenant_id?: string | null;
  email?: string | null;
  fulfilled?: boolean;
}

export interface BillingSignupCheckoutBody {
  email: string;
  password: string;
  organisation_name: string;
  country: string;
  plan_code: "free" | "studio";
  industry?: string;
  full_name?: string;
  signup_token?: string;
  signup_source?: "public" | "invite";
}

export interface BillingPlansCatalog {
  country: string;
  region: string;
  currency_code: string;
  plans: PlanInfo[];
  platform_billing_enabled: boolean;
}

export interface BillingUsageHistory {
  items: CreditLedgerEntry[];
  total: number;
  page: number;
  pages: number;
}

export interface PlatformCreditSettings {
  credits_per_page: number;
  universal_credits_per_page: boolean;
  topup_factor_in: number;
  topup_factor_sg: number;
  topup_factor_au: number;
}

export interface PlatformPromptSummary {
  key: string;
  label: string;
  group: string;
  description: string;
  placeholders: string[];
  default_body: string;
  body: string;
  version: number | null;
  is_overridden: boolean;
  updated_at?: string | null;
  notes?: string | null;
}

export interface PlatformPromptVersionItem {
  version: number;
  body: string;
  notes?: string | null;
  created_at?: string | null;
  created_by_user_id?: number | null;
  is_active: boolean;
}

export interface PlatformPromptVersionList {
  items: PlatformPromptVersionItem[];
}

export interface PipelineAuditStep {
  stage: string;
  at: string | null;
  when: string;
  detail: string;
  state: "done" | "pending" | "fail" | "skipped";
}

export type PipelineActivePath = "understood" | "not_understood" | "unknown";

export interface InvoicePipelineResponse {
  steps: PipelineAuditStep[];
  active_path?: PipelineActivePath;
}

export interface InvoiceClassificationScoreBreakdown {
  rule_strength?: number;
  field_completeness?: number;
  parse_score?: number;
  heading_alignment?: number;
  confidence?: number;
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
  llm_suggested_dt?: string;
  llm_confidence?: number;
  llm_reasoning?: string;
  policy_winner_dt?: string;
  policy_winner_confidence?: number;
  policy_scores?: Array<{
    code: string;
    confidence: number;
    required_missing?: string[];
    absent_violations?: string[];
  }>;
  confirmed_dt?: string;
  confirmed_confidence?: number;
  review_reasons?: string[];
  compare_passed?: boolean;
  auto_route_min_confidence?: number;
  org_auto_route_min_confidence?: number;
  dt_min_route_confidence?: number;
  perspective?: string;
  citation_failed?: string[];
  citation_verified?: string[];
}

export interface BankAccount {
  id: number;
  name: string;
  currency: string;
  account_mask: string | null;
  coa_account_code: string;
  coa_account_name: string;
  connection_type: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface BankFeedImport {
  id: number;
  bank_account_id: number;
  source: string;
  filename: string | null;
  file_sha256: string;
  status: string;
  row_count: number;
  accepted_count: number;
  duplicate_count: number;
  error_count: number;
  categorized_count?: number;
  extracted_count?: number;
  error_report: Record<string, unknown> | unknown[] | null;
  actor_user_id: number | null;
  imported_at: string;
  reused_existing: boolean;
}

export interface BankFeedImportList {
  items: BankFeedImport[];
}

export interface BankTransactionNote {
  id: number;
  bank_transaction_id: number;
  body: string;
  author_user_id: number | null;
  created_at: string;
}

export interface BankTransactionMatch {
  id: number;
  bank_transaction_id: number;
  matched_type: string;
  matched_id: number;
  allocated_amount: number;
  match_confidence: number;
  match_method: string;
  match_reasons: Record<string, unknown> | null;
  matched_by: string | null;
  matched_at: string;
  unmatched_at: string | null;
  unmatch_reason: string | null;
  party_name?: string | null;
  invoice_no?: string | null;
  display_label?: string | null;
}

export interface BankMatchTarget {
  id: number;
  matched_type: "payment" | "collection";
  party_name: string | null;
  invoice_no: string | null;
  amount: number;
  currency: string;
  status: string;
  display_label: string;
}

export interface BankTransaction {
  id: number;
  bank_account_id: number;
  import_id: number | null;
  txn_date: string;
  posted_date: string | null;
  description: string;
  amount: number;
  currency: string;
  money_flow: "in" | "out";
  balance: number | null;
  reference: string | null;
  match_status: string;
  category_coa: string | null;
  category_source?: "rule" | "manual" | null;
  category_rule_name?: string | null;
  category_matched_snippet?: string | null;
  possible_duplicate_of: number[] | null;
  posted_journal_batch_id?: number | null;
  created_at: string;
  updated_at: string;
  matches: BankTransactionMatch[];
}

export interface BankCategorizeRunItem {
  transaction_id: number;
  categorized: boolean;
  category_coa: string | null;
  rule_id: string | null;
  rule_name: string | null;
}

export interface BankCategorizeRunResult {
  items: BankCategorizeRunItem[];
  categorized_count: number;
}

export interface BankTransactionList {
  items: BankTransaction[];
}

export interface BankMatchRunItem {
  transaction_id: number;
  status: string;
  matches_written: number;
  auto_matched: boolean;
  tie_demoted: boolean;
}

export interface BankMatchRunResult {
  items: BankMatchRunItem[];
}

export type BankFeedQueueTab = "reconcile" | "matched" | "posted" | "excluded" | "unsettled";

export interface UnsettledSettlement {
  entity_type: "payment" | "collection";
  entity_id: number;
  invoice_id: number;
  invoice_no: string | null;
  party_name: string | null;
  amount: number;
  currency: string;
  settled_date: string;
  days_since_settled: number;
  has_suggested_bank_match: boolean;
  allocated_bank_amount: number;
  gross_amount: number | null;
  grace_days: number;
}

export interface UnsettledSettlementList {
  items: UnsettledSettlement[];
  grace_days: number;
  lookback_months: number;
}

export interface UnsettledSettlementCount {
  count: number;
  grace_days: number;
}
