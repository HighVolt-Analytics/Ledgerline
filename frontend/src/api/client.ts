import type {
  ApprovalPolicy,
  BillingState,
  BillingSignupCheckoutBody,
  BillingPlansCatalog,
  BillingLedgerCategory,
  BillingUsageHistory,
  CheckoutSessionResult,
  CheckoutStatusResult,
  PlatformCreditSettings,
  PlatformPromptSummary,
  PlatformPromptVersionList,
  AuditLogEntry,
  ActivityItem,
  ApiEnvelope,
  AppSettings,
  BankAccount,
  BankCategorizeRunResult,
  BankFeedImport,
  BankFeedImportList,
  BankTransactionNote,
  BankMatchRunResult,
  BankTransaction,
  BankTransactionList,
  BankTransactionMatch,
  BankMatchTarget,
  UnsettledSettlementCount,
  UnsettledSettlementList,
  AccountingIntegrationsStatus,
  XeroConnectionsResponse,
  XeroInvoiceStatus,
  XeroReadiness,
  XeroSelectConnectionResult,
  XeroSyncContactsResult,
  XeroSyncSettingsResult,
  XeroVerifyResult,
  XeroAccountRow,
  XeroTaxRateRow,
  XeroContactRow,
  XeroSyncHistoryRow,
  XeroExportHistoryRow,
  XeroMasterTotals,
  XeroMasterListMeta,
  XeroMappingRow,
  XeroTrackingCategoryRow,
  XeroExportLedgerRow,
  XeroExportQueueItem,
  AuthUser,
  ConnectedMailbox,
  MailboxBackfillJob,
  MailboxBackfillQueued,
  MailboxConnectionRequest,
  MailboxConnectionRequestAction,
  MailboxInvitePreview,
  MailProvider,
  DailyReconciliation,
  NavBadges,
  NotificationsResponse,
  PaymentApi,
  PaymentExecutionInstructionApi,
  PaymentExecutionInstructionExportApi,
  PaymentExecutionReadinessResponse,
  PaymentMarkPaidManualPayload,
  PurchaseOrderApi,
  PurchaseWorkspaceKpis,
  SalesWorkspaceKpis,
  PurchaseDossier,
  SalesOrderApi,
  SalesDossierResponse,
  CollectionApi,
  CollectionMarkReceivedPayload,
  CollectionWorkspaceKpis,
  PaymentWorkspaceKpis,
  Customer,
  DashboardOverview,
  DashboardStats,
  PositionLiquidityDashboard,
  EfficiencyAutomationDashboard,
  CashLiabilityOutlookDashboard,
  BudgetConcentrationRiskDashboard,
  CfoAlertsDashboard,
  ProcessEfficiencyTrendsDashboard,
  ReportsAnalytics,
  ReportCatalogResponse,
  ReportColumnLayoutCreate,
  ReportColumnLayoutItem,
  ReportColumnLayoutUpdate,
  ReportDocumentRow,
  ReportExportRequest,
  ReportPreview,
  EmployeeAdvanceSettlementRow,
  EmployeeBudgetUtilizationRow,
  DepartmentBudgetRow,
  DepartmentBudgetUtilizationRow,
  EmployeeExpenseSummaryRow,
  EmployeeSpendDetailRow,
  EmployeeAdvanceDetailRow,
  SubledgerBalancesResponse,
  Invoice,
  InvoiceDetails,
  LedgerLinkResponse,
  LedgerLinkExports,
  ReconDayOverviewRow,
  InvoiceUpdatePayload,
  Tenant,
  PlatformTenantSummary,
  PlatformTenantDetail,
  PlatformTenantModule,
  MatrixRow,
  InvoicePipelineResponse,
  InvoiceClassificationAudit,
  ProcessingStatus,
  RuleBookConfig,
  BankFileSettings,
  RegistryFieldsResponse,
  RuleBookChangelogEntry,
  RuleBookRulesPayload,
  ReconciliationOverview,
  ReconciliationDayDetail,
  TokenResponse,
  TenantMembersList,
  TenantMember,
  TenantInviteCreated,
  InvitePreview,
  InviteAcceptResult,
  MasterConfirmationPreview,
  MasterConfirmationSaveResult,
  InstitutionSettings,
  OrgAiBrief,
  ChartOfAccountsPayload,
  OrgTaxRateWrite,
  TaxRatesPayload,
  OnboardingStatus,
  UserPermissions,
  Vendor,
  VendorActivity,
  VendorPayoutMethod,
  VendorPayoutMethodCreate,
  VendorPayoutMethodUpdate,
  VaultTreeResponse,
  VaultFilesResponse,
  VaultDocumentSetsResponse,
  VaultMigrateResponse,
  WalletSummary,
  StripeAccount,
  StripeBalanceResponse,
  StripeConnectResponse,
  StripeOnboardingLinkResponse,
  StripeOAuthUrlResponse,
  StripeDisconnectResponse,
  StripeGlobalPayoutsReadinessResponse,
  StripeReadinessResponse,
  StripeTransaction,
  PaypalBalanceResponse,
  PaypalConnectResponse,
  PaypalDisconnectResponse,
  PaypalPayoutAttempt,
  PaypalPayoutRequest,
  PaypalReadinessResponse,
  PaypalTransactionsResponse,
  WhatsappStatus,
  ViberStatus,
} from "./types";

import { resolveApiBase } from "@/lib/apiBase";
import { tenantIdFromToken } from "@/lib/authToken";
import { getAccessToken, getRefreshToken } from "@/lib/authSession";
import type { DashboardPeriod } from "@/lib/dashboardPeriod";

function dashboardApiPath(path: string, period?: DashboardPeriod): string {
  if (!period) return path;
  return `${path}?period=${encodeURIComponent(period)}`;
}

/** Public URL prefix; endpoint paths include /api (e.g. BASE + /api/auth/login). */
const BASE = resolveApiBase();

/** Dedupe concurrent GETs only — no response cache (avoids cross-tenant bleed). */
const GET_CACHE_MS = 0;
const inflightGets = new Map<string, Promise<unknown>>();
const getCache = new Map<string, { data: unknown; at: number }>();
/** Bumped on mutation so in-flight GETs cannot repopulate cache with stale rows. */
let getCacheGeneration = 0;

let authToken: string | null = null;
let authUser: AuthUser | null = null;
let unauthorizedHandler: (() => void | Promise<void>) | null = null;
let handlingUnauthorized = false;

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type EmployeeImportMode = "register" | "payment";

export interface EmployeeImportRowError {
  row_number: number;
  email: string | null;
  message: string;
}

export interface EmployeeImportRowPreview {
  row_number: number;
  email: string;
  name: string | null;
  action: string;
  detail: string;
}

export interface EmployeeImportResult {
  mode: EmployeeImportMode;
  dry_run: boolean;
  created: number;
  updated: number;
  skipped: number;
  errors: EmployeeImportRowError[];
  previews: EmployeeImportRowPreview[];
}

export interface DepartmentBudgetImportRowError {
  row_number: number;
  parent_gl: string | null;
  message: string;
}

export interface DepartmentBudgetImportRowPreview {
  row_number: number;
  parent_gl: string;
  period_kind: string;
  period_key: string;
  action: string;
  detail: string;
}

export interface DepartmentBudgetImportResult {
  dry_run: boolean;
  created: number;
  updated: number;
  skipped: number;
  errors: DepartmentBudgetImportRowError[];
  previews: DepartmentBudgetImportRowPreview[];
}

export function setUnauthorizedHandler(handler: (() => void | Promise<void>) | null) {
  unauthorizedHandler = handler;
}

async function notifyUnauthorized() {
  if (!authToken || !unauthorizedHandler || handlingUnauthorized) return;
  handlingUnauthorized = true;
  try {
    await unauthorizedHandler();
  } finally {
    handlingUnauthorized = false;
  }
}

const AUTH_RETRY_PATHS = new Set([
  "/api/auth/me",
  "/api/auth/refresh",
  "/api/auth/login",
  "/api/auth/logout",
]);

/** Pre-auth endpoints that must not require a resolved tenant id. */
const TENANT_EXEMPT_API_PATHS = new Set([
  "/api/auth/login",
  "/api/auth/verify-otp",
  "/api/auth/resend-otp",
  "/api/auth/select-tenant",
  "/api/auth/forgot-password",
  "/api/auth/reset-password",
  "/api/auth/refresh",
]);

/** Public invite accept and billing signup flows (no tenant session). */
const TENANT_EXEMPT_API_PREFIXES = [
  "/api/auth/invite/",
  "/api/mailboxes/invites/",
  "/api/billing/signup/",
  "/api/billing/plans",
  "/api/master-confirm/",
];

export function apiPathWithoutQuery(path: string): string {
  return path.split("?")[0] ?? path;
}

export function isTenantScopedApiPath(path: string): boolean {
  if (!path.startsWith("/api/")) return false;
  const bare = apiPathWithoutQuery(path);
  if (AUTH_RETRY_PATHS.has(bare) || TENANT_EXEMPT_API_PATHS.has(bare)) return false;
  if (TENANT_EXEMPT_API_PREFIXES.some((prefix) => bare.startsWith(prefix))) return false;
  return true;
}

function requireTenantIdForPath(path: string): string | null {
  if (!isTenantScopedApiPath(path)) return resolveActiveTenantId();
  const tid = resolveActiveTenantId();
  if (!tid) {
    throw new ApiError("Tenant scope required", 401);
  }
  return tid;
}

async function tryRefreshSession(): Promise<boolean> {
  if (!getRefreshToken()) return false;
  try {
    const { refreshAccessTokenSingleFlight } = await import("@/lib/authTokenRefresh");
    await refreshAccessTokenSingleFlight();
    return true;
  } catch {
    void notifyUnauthorized();
    return false;
  }
}

/** In-memory access token only — never read sessionStorage here for scope decisions. */
export function getAuthToken(): string | null {
  return authToken;
}

/**
 * Active tenant from in-memory JWT first. Profile is only a fallback when no JWT is loaded.
 * Never prefer profile over a present JWT (avoids header/cache scope drift mid-switch).
 */
export function getActiveTenantId(): string | null {
  if (authToken) {
    const fromJwt = tenantIdFromToken(authToken);
    if (fromJwt) return fromJwt;
  }
  const fromSession = tenantIdFromToken(getAccessToken());
  if (fromSession) return fromSession;
  if (authUser?.tenant_id) return String(authUser.tenant_id);
  return null;
}

export function setAuthToken(token: string | null) {
  authToken = token;
  clearGetCache();
}

export function setAuthUser(user: AuthUser | null) {
  const prevTenantId = getActiveTenantId();
  authUser = user;
  const nextTenantId = getActiveTenantId();
  if (prevTenantId !== nextTenantId) {
    clearGetCache();
  }
}

function resolveActiveTenantId(): string | null {
  return getActiveTenantId();
}

/** Drop in-flight GET results only when the active tenant id changed. */
function assertSameTenantActive(requestTenantId: string | null): void {
  if (resolveActiveTenantId() !== requestTenantId) {
    throw new ApiError("Tenant scope changed", 409);
  }
}

function canRememberGetCache(cacheGeneration: number): boolean {
  return cacheGeneration === getCacheGeneration;
}

function getScopedAuthHeaders(init?: RequestInit): Headers {
  const headers = withAuthHeaders(init);
  const tid = resolveActiveTenantId();
  if (tid) {
    headers.set("X-Tenant-Id", tid);
  }
  return headers;
}

/** Bearer + X-Tenant-Id for raw fetch calls outside the api client (e.g. during OAuth hydrate). */
export function getScopedAuthHeadersForToken(
  accessToken: string,
  init?: RequestInit
): Headers {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  const tid = tenantIdFromToken(accessToken);
  if (tid) {
    headers.set("X-Tenant-Id", tid);
  }
  return headers;
}

export function clearGetCache() {
  getCacheGeneration += 1;
  getCache.clear();
  inflightGets.clear();
}

function getRequestKey(path: string, method: string): string | null {
  const tid = resolveActiveTenantId();
  if (!tid) return null;
  return `${tid}:${method}:${path}`;
}

function invalidateGetCache() {
  getCacheGeneration += 1;
  getCache.clear();
  inflightGets.clear();
}

function bustGetCache(path: string, method = "GET") {
  getCacheGeneration += 1;
  const key = getRequestKey(path, method);
  if (key) getCache.delete(key);
  const metaKey = getRequestKey(`${path}#meta`, method);
  if (metaKey) getCache.delete(metaKey);
}

function bustGetCacheByPrefix(pathPrefix: string, method = "GET") {
  getCacheGeneration += 1;
  const needle = `:${method}:${pathPrefix}`;
  for (const key of Array.from(getCache.keys())) {
    if (key.includes(needle)) getCache.delete(key);
  }
  for (const key of Array.from(inflightGets.keys())) {
    if (key.includes(needle)) inflightGets.delete(key);
  }
}

function rememberGetCache(key: string, data: unknown) {
  getCache.set(key, { data, at: Date.now() });
}

export type FreshRequestOptions = { fresh?: boolean; revealBank?: boolean };

export type ApiRequestOptions = RequestInit & { timeoutMs?: number };

function withAuthHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  const token = authToken ?? getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

/** Load in-memory token from localStorage before the first React render. */
export function hydrateAuthTokenFromSession(): void {
  if (authToken) return;
  if (typeof localStorage === "undefined") return;
  const token = getAccessToken();
  if (token) authToken = token;
}

if (typeof localStorage !== "undefined") {
  hydrateAuthTokenFromSession();
}

async function parseErrorResponse(res: Response): Promise<string> {  /* Convert backend error response → readable message */
  let msg = res.statusText;
  try {
    const body = await res.json();
    const detail = body.detail ?? body.error?.message;
    if (typeof detail === "string") {
      msg = detail;
    } else if (Array.isArray(detail)) {
      const parts = detail.map((d: { msg?: string; loc?: unknown[] }) => {
        const field = Array.isArray(d.loc)
          ? d.loc.filter((x) => x !== "body").join(".")
          : "";
        const reason = d.msg ?? JSON.stringify(d);
        return field ? `${field} — ${reason}` : reason;
      });
      msg = parts.length ? `Validation error: ${parts.join("; ")}` : res.statusText;
    } else if (detail != null) {
      msg = JSON.stringify(detail);
    }
  } catch {
    /* ignore */
  }
  return msg;
}

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      return star[1].trim();
    }
  }
  const plain = /filename="?([^";\n]+)"?/i.exec(header);
  return plain?.[1]?.trim() || fallback;
}

function normalizePreviewBlob(blob: Blob, filename: string): Blob {
  if (blob.type && blob.type !== "application/octet-stream") {
    return blob;
  }
  const lower = filename.toLowerCase();
  if (lower.endsWith(".pdf")) return new Blob([blob], { type: "application/pdf" });
  if (lower.endsWith(".png")) return new Blob([blob], { type: "image/png" });
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
    return new Blob([blob], { type: "image/jpeg" });
  }
  return blob;
}

export function saveBlobAsFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function requestBlob(
  path: string,
  init?: RequestInit,
  fallbackFilename = "download"
): Promise<{ blob: Blob; filename: string; headers: Headers }> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: getScopedAuthHeaders(init) });
  if (!res.ok) {
    const msg = await parseErrorResponse(res);
    if (res.status === 401) {
      void notifyUnauthorized();
    }
    throw new ApiError(msg, res.status);
  }
  return {
    blob: await res.blob(),
    filename: filenameFromDisposition(res.headers.get("Content-Disposition"), fallbackFilename),
    headers: res.headers,
  };
}

async function fetchEnvelope<T>(
  path: string,
  init?: ApiRequestOptions,
  retriedAfterRefresh = false
): Promise<T> {
  const { timeoutMs, ...fetchInit } = init ?? {};
  const controller = timeoutMs != null && timeoutMs > 0 ? new AbortController() : null;
  const timer =
    controller != null
      ? window.setTimeout(() => controller.abort(), timeoutMs)
      : null;
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...fetchInit,
      signal: controller?.signal,
      headers: getScopedAuthHeaders(fetchInit),
    });
    if (!res.ok) {
      const msg = await parseErrorResponse(res);
      if (res.status === 401 && !retriedAfterRefresh && !AUTH_RETRY_PATHS.has(path)) {
        const refreshed = await tryRefreshSession();
        if (refreshed) {
          return fetchEnvelope<T>(path, init, true);
        }
      }
      if (res.status === 401 && (authToken ?? getAccessToken()) && !AUTH_RETRY_PATHS.has(path)) {
        void notifyUnauthorized();
      }
      throw new ApiError(msg, res.status);
    }
    if (res.status === 204) return undefined as T;
    const json = (await res.json()) as ApiEnvelope<T>;
    if (json.error) throw new Error(json.error.message);
    return json.data;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(
        "The request took too long. Try fewer files or use text-based PDFs.",
        408
      );
    }
    throw err;
  } finally {
    if (timer != null) window.clearTimeout(timer);
  }
}

async function request<T>(path: string, init?: ApiRequestOptions): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const requestTenantId = requireTenantIdForPath(path);

  if (method !== "GET") {
    invalidateGetCache();
    const data = await fetchEnvelope<T>(path, init);
    assertSameTenantActive(requestTenantId);
    return data;
  }

  const key = getRequestKey(path, method);
  if (key) {
    const cached = getCache.get(key);
    if (cached && Date.now() - cached.at < GET_CACHE_MS) {
      assertSameTenantActive(requestTenantId);
      return cached.data as T;
    }

    const inflight = inflightGets.get(key);
    if (inflight) return inflight as Promise<T>;
  }

  const cacheGeneration = getCacheGeneration;
  const inflightKey = key ?? `__no_cache__:${method}:${path}`;
  const promise = fetchEnvelope<T>(path, init)
    .then((data) => {
      assertSameTenantActive(requestTenantId);
      if (key && canRememberGetCache(cacheGeneration)) {
        rememberGetCache(key, data);
      }
      return data;
    })
    .finally(() => {
      inflightGets.delete(inflightKey);
    });

  inflightGets.set(inflightKey, promise);
  return promise;
}

async function requestWithMeta<T>(
  path: string,
  init?: RequestInit
): Promise<{ data: T; meta: ApiEnvelope<T>["meta"] }> {
  const method = (init?.method ?? "GET").toUpperCase();
  const requestTenantId = requireTenantIdForPath(path);
  const key = getRequestKey(`${path}#meta`, method);

  if (method === "GET") {
    if (key) {
      const cached = getCache.get(key);
      if (cached && Date.now() - cached.at < GET_CACHE_MS) {
        assertSameTenantActive(requestTenantId);
        return cached.data as { data: T; meta: ApiEnvelope<T>["meta"] };
      }
      const inflight = inflightGets.get(key);
      if (inflight) {
        return inflight as Promise<{ data: T; meta: ApiEnvelope<T>["meta"] }>;
      }
    }
  } else {
    invalidateGetCache();
  }

  const cacheGeneration = getCacheGeneration;
  const inflightKey = key ?? `__no_cache__:${method}:${path}#meta`;
  const promise = (async () => {
    const res = await fetch(`${BASE}${path}`, { ...init, headers: getScopedAuthHeaders(init) });
    if (!res.ok) {
      const msg = await parseErrorResponse(res);
      if (res.status === 401) {
        void notifyUnauthorized();
      }
      throw new ApiError(msg, res.status);
    }
    const json = (await res.json()) as ApiEnvelope<T>;
    if (json.error) throw new Error(json.error.message);
    assertSameTenantActive(requestTenantId);
    return { data: json.data, meta: json.meta };
  })();

  if (method === "GET") {
    const tracked = promise.then((payload) => {
      assertSameTenantActive(requestTenantId);
      if (key && canRememberGetCache(cacheGeneration)) {
        rememberGetCache(key, payload);
      }
      return payload;
    });
    inflightGets.set(inflightKey, tracked);
    return tracked.finally(() => inflightGets.delete(inflightKey));
  }

  return promise;
}

export const api = {
  logout: (refreshToken?: string) =>
    request<{ message: string }>("/api/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
    }),
  refreshSession: (refreshToken: string) =>
    request<TokenResponse>("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),
  me: () => request<AuthUser>("/api/auth/me"),
  getInstitutionSettings: () =>
    request<InstitutionSettings>("/api/tenants/current/institution"),
  updateInstitutionSettings: (body: {
    name?: string;
    country?: string;
    currency?: string;
    timezone?: string;
    locale?: string;
    custom_bundle_field_key?: string;
    labor_rate_per_hour?: number;
  }) =>
    request<InstitutionSettings>("/api/tenants/current/institution", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getOrgAiBrief: () => request<OrgAiBrief>("/api/tenants/current/org-ai-brief"),
  updateOrgAiBrief: (body: OrgAiBrief) =>
    request<OrgAiBrief>("/api/tenants/current/org-ai-brief", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getChartOfAccounts: () =>
    request<ChartOfAccountsPayload>("/api/tenants/current/chart-of-accounts"),
  updateChartOfAccounts: (body: ChartOfAccountsPayload) =>
    request<ChartOfAccountsPayload>("/api/tenants/current/chart-of-accounts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  syncChartOfAccounts: () =>
    request<ChartOfAccountsPayload>("/api/tenants/current/chart-of-accounts/sync", {
      method: "POST",
    }),
  createXeroChartOfAccount: (body: {
    code: string;
    name: string;
    type: string;
    sub_type: string;
    sub_ledgers?: { code: string; name: string; origin?: string }[];
  }) =>
    request<ChartOfAccountsPayload>("/api/tenants/current/chart-of-accounts/xero", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateXeroChartOfAccount: (
    accountId: string,
    body: {
      code: string;
      name: string;
      type: string;
      sub_type: string;
      sub_ledgers?: { code: string; name: string; origin?: string }[];
    }
  ) =>
    request<ChartOfAccountsPayload>(
      `/api/tenants/current/chart-of-accounts/xero/${encodeURIComponent(accountId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  deleteXeroChartOfAccount: (accountId: string) =>
    request<ChartOfAccountsPayload>(
      `/api/tenants/current/chart-of-accounts/xero/${encodeURIComponent(accountId)}`,
      { method: "DELETE" }
    ),
  pullXeroChartOfAccount: (accountId: string) =>
    request<ChartOfAccountsPayload>(
      `/api/tenants/current/chart-of-accounts/xero/${encodeURIComponent(accountId)}/pull`,
      { method: "POST" }
    ),
  getTaxRates: () => request<TaxRatesPayload>("/api/tenants/current/tax-rates"),
  syncTaxRates: () =>
    request<TaxRatesPayload>("/api/tenants/current/tax-rates/sync", { method: "POST" }),
  createTaxRate: (body: OrgTaxRateWrite) =>
    request<TaxRatesPayload>("/api/tenants/current/tax-rates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: body.display_name,
        tax_type: body.tax_type,
        components: body.components,
      }),
    }),
  deleteTaxRate: (rateId: string) =>
    request<TaxRatesPayload>(`/api/tenants/current/tax-rates/${encodeURIComponent(rateId)}`, {
      method: "DELETE",
    }),
  updateTaxRate: (rateId: string, body: OrgTaxRateWrite) =>
    request<TaxRatesPayload>(`/api/tenants/current/tax-rates/${encodeURIComponent(rateId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: body.display_name,
        tax_type: body.tax_type,
        components: body.components,
      }),
    }),
  updateTaxRates: (body: { tax_rates: OrgTaxRateWrite[] }) =>
    request<TaxRatesPayload>("/api/tenants/current/tax-rates", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getOnboardingStatus: () => request<OnboardingStatus>("/api/tenants/current/onboarding"),
  updateOnboarding: (body: { country?: string; industry?: string; complete?: boolean }) =>
    request<OnboardingStatus>("/api/tenants/current/onboarding", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getMyPermissions: () => request<UserPermissions>("/api/auth/me/permissions"),
  listTenantMembers: () => request<TenantMembersList>("/api/tenants/current/members"),
  inviteTenantMember: (body: { email: string; full_name: string; role: string }) =>
    request<TenantInviteCreated>("/api/tenants/current/members/invite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateTenantMemberRole: (userId: number, role: string) =>
    request<TenantMember>("/api/tenants/current/members/" + userId, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    }),
  deactivateTenantMember: (userId: number) =>
    request<{ message: string }>("/api/tenants/current/members/" + userId, {
      method: "DELETE",
    }),
  activateTenantMember: (userId: number) =>
    request<TenantMember>("/api/tenants/current/members/" + userId + "/activate", {
      method: "POST",
    }),
  revokeTenantInvite: (inviteId: number) =>
    request<{ message: string }>("/api/tenants/current/members/invites/" + inviteId, {
      method: "DELETE",
    }),
  previewTenantInvite: (token: string) =>
    request<InvitePreview>(`/api/auth/invite/preview?token=${encodeURIComponent(token)}`),
  acceptTenantInvite: (body: { token: string; password: string; full_name?: string }) =>
    request<InviteAcceptResult>("/api/auth/invite/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  previewMasterConfirmation: (token: string) =>
    request<MasterConfirmationPreview>(
      `/api/master-confirm/preview?token=${encodeURIComponent(token)}`
    ),
  saveMasterConfirmation: (body: { token: string; fields: Record<string, unknown> }) =>
    request<MasterConfirmationSaveResult>("/api/master-confirm/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listTenants: () => request<Tenant[]>("/api/tenants"),
  listOrganisations: () => request<Tenant[]>("/api/tenants"),
  createTenant: (body: { name: string; slug: string; currency?: string }) =>
    request<Tenant>("/api/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createOrganisation: (body: { name: string; slug: string; currency?: string }) =>
    request<Tenant>("/api/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  switchTenant: (tenantId: string) =>
    request<TokenResponse>("/api/auth/switch-tenant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenantId }),
    }),
  switchOrganisation: (tenantId: string) =>
    request<TokenResponse>("/api/auth/switch-tenant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenantId }),
    }),

  listPlatformTenants: () => request<PlatformTenantSummary[]>("/api/platform/tenants"),
  getPlatformTenant: (tenantId: string) =>
    request<PlatformTenantDetail>(`/api/platform/tenants/${tenantId}`),
  listPlatformTenantMembers: (tenantId: string) =>
    request<TenantMembersList>(`/api/platform/tenants/${tenantId}/members`),
  createPlatformTenant: (body: import("@/api/types").CreatePlatformTenantBody) =>
    request<PlatformTenantDetail>("/api/platform/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  invitePlatformTenantAdmin: (tenantId: string, body: import("@/api/types").PlatformInviteAdminBody) =>
    request<TenantInviteCreated>(`/api/platform/tenants/${tenantId}/invite-admin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updatePlatformTenant: (
    tenantId: string,
    body: {
      name?: string;
      is_active?: boolean;
      lifecycle_status?: string;
      modules?: PlatformTenantModule[];
    }
  ) =>
    request<PlatformTenantDetail>(`/api/platform/tenants/${tenantId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deletePlatformTenant: (tenantId: string, confirmSlug: string) =>
    request<{ status: string }>(`/api/platform/tenants/${tenantId}/delete-permanently`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_slug: confirmSlug }),
    }),

  listMailboxes: (options?: FreshRequestOptions) => {
    const path = "/api/mailboxes";
    if (options?.fresh) bustGetCache(path);
    return request<ConnectedMailbox[]>(path);
  },
  listMailboxConnectionRequests: (options?: FreshRequestOptions) => {
    const path = "/api/mailboxes/requests";
    if (options?.fresh) bustGetCache(path);
    return request<MailboxConnectionRequest[]>(path);
  },
  createMailboxConnectionRequest: (body: {
    email: string;
    display_name?: string;
    message?: string;
  }) => {
    bustGetCache("/api/mailboxes/requests");
    return request<MailboxConnectionRequestAction>("/api/mailboxes/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  resendMailboxConnectionRequest: (id: number) => {
    bustGetCache("/api/mailboxes/requests");
    return request<MailboxConnectionRequestAction>(`/api/mailboxes/requests/${id}/resend`, {
      method: "POST",
    });
  },
  getMailboxConnectionInviteLink: (id: number) =>
    request<{ connect_url: string }>(`/api/mailboxes/requests/${id}/link`),
  previewMailboxInvite: (token: string) =>
    request<MailboxInvitePreview>(
      `/api/mailboxes/invites/preview?token=${encodeURIComponent(token)}`
    ),
  startMailboxInviteOAuth: (token: string, provider?: MailProvider) =>
    request<{ authorize_url: string; mail_provider?: MailProvider }>(
      `/api/mailboxes/invites/authorize?token=${encodeURIComponent(token)}${
        provider ? `&provider=${encodeURIComponent(provider)}` : ""
      }`
    ),
  getMailboxAdminConsentUrl: () =>
    request<{ admin_consent_url: string; instructions: string }>(
      "/api/mailboxes/oauth/admin-consent-url"
    ),
  startMailboxOAuth: () =>
    request<{ authorize_url: string }>("/api/mailboxes/oauth/authorize"),
  addMailbox: (email: string, display_name?: string) =>
    request<ConnectedMailbox>("/api/mailboxes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, display_name }),
    }),
  removeMailbox: (id: number) => {
    bustGetCache("/api/mailboxes");
    return request<void>(`/api/mailboxes/${id}`, { method: "DELETE" });
  },
  toggleMailbox: (id: number) =>
    request<ConnectedMailbox>(`/api/mailboxes/${id}/toggle`, { method: "PATCH" }),
  startMailboxBackfill: (
    mailboxId: number,
    body: { from_date: string; to_date?: string; mark_processed?: boolean }
  ) =>
    request<MailboxBackfillQueued>(`/api/mailboxes/${mailboxId}/backfill`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getMailboxBackfillStatus: (mailboxId: number, jobId: number, options?: FreshRequestOptions) => {
    const path = `/api/mailboxes/${mailboxId}/backfill/${jobId}`;
    if (options?.fresh) bustGetCache(path);
    return request<MailboxBackfillJob>(path);
  },

  getWhatsappStatus: (options?: FreshRequestOptions) => {
    const path = "/api/integrations/whatsapp/status";
    if (options?.fresh) bustGetCache(path);
    return request<WhatsappStatus>(path);
  },
  getWhatsappAuthorizeUrl: () =>
    request<{ authorize_url: string }>("/api/integrations/whatsapp/authorize-url"),
  disconnectWhatsapp: (id: number) => {
    bustGetCache("/api/integrations/whatsapp/status");
    return request<{ disconnected: boolean; id: number }>(
      `/api/integrations/whatsapp/disconnect/${id}`,
      { method: "DELETE" }
    );
  },
  testWhatsappConnection: (id: number) => {
    bustGetCache("/api/integrations/whatsapp/status");
    return request<{
      ok: boolean;
      integration_health: string;
      warnings: string[];
      profile: Record<string, unknown>;
    }>(`/api/integrations/whatsapp/test/${id}`, { method: "POST" });
  },

  getAccountingIntegrationsStatus: (options?: FreshRequestOptions) => {
    const path = "/api/integrations/status";
    if (options?.fresh) bustGetCache(path);
    return request<AccountingIntegrationsStatus>(path);
  },
  connectXero: () =>
    request<{ connect_url: string }>("/api/integrations/xero/connect"),
  connectQuickBooks: () =>
    request<{ connect_url: string }>("/api/integrations/quickbooks/connect"),
  disconnectAccountingIntegration: (provider: "xero" | "quickbooks_online") => {
    bustGetCache("/api/integrations/status");
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{ disconnected: boolean; provider: string }>(
      `/api/integrations/${provider}/disconnect`,
      { method: "POST" }
    );
  },
  getXeroReadiness: (options?: FreshRequestOptions) => {
    const path = "/api/integrations/xero/readiness";
    if (options?.fresh) bustGetCache(path);
    return request<XeroReadiness>(path);
  },
  verifyXeroConnection: () => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<XeroVerifyResult>("/api/integrations/xero/verify");
  },
  getXeroConnections: (options?: FreshRequestOptions) => {
    const path = "/api/integrations/xero/connections";
    if (options?.fresh) bustGetCache(path);
    return request<XeroConnectionsResponse>(path);
  },
  selectXeroConnection: (xero_connection_id: string) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    bustGetCache("/api/integrations/status");
    return request<XeroSelectConnectionResult>("/api/integrations/xero/connections/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ xero_connection_id }),
    });
  },
  syncXeroSettings: () => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<XeroSyncSettingsResult>("/api/integrations/xero/sync/settings", {
      method: "POST",
    });
  },
  syncXeroContacts: () => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<XeroSyncContactsResult>("/api/integrations/xero/sync/contacts", {
      method: "POST",
    });
  },
  getXeroAccounts: (params?: { search?: string; status?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroAccountRow[] }>(
      `/api/integrations/xero/accounts${q ? `?${q}` : ""}`
    );
  },
  getXeroTaxRates: (params?: { search?: string; status?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroTaxRateRow[] }>(
      `/api/integrations/xero/tax-rates${q ? `?${q}` : ""}`
    );
  },
  getXeroContactsList: (params?: {
    search?: string;
    status?: string;
    mapping_status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.status) qs.set("status", params.status);
    if (params?.mapping_status) qs.set("mapping_status", params.mapping_status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroContactRow[] }>(
      `/api/integrations/xero/contacts${q ? `?${q}` : ""}`
    );
  },
  createXeroContact: (body: { legal_name: string; supplier_key?: string }) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{
      created: boolean;
      reused: boolean;
      contact_id: string;
      name?: string | null;
      reason?: string | null;
    }>("/api/integrations/xero/contacts/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  getXeroReferenceAccounts: (params?: {
    search?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroAccountRow[] }>(
      `/api/integrations/xero/reference/accounts${q ? `?${q}` : ""}`
    );
  },
  getXeroReferenceTaxRates: (params?: {
    search?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroTaxRateRow[] }>(
      `/api/integrations/xero/reference/tax-rates${q ? `?${q}` : ""}`
    );
  },
  getXeroReferenceContacts: (params?: {
    search?: string;
    status?: string;
    mapping_status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.status) qs.set("status", params.status);
    if (params?.mapping_status) qs.set("mapping_status", params.mapping_status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroContactRow[] }>(
      `/api/integrations/xero/reference/contacts${q ? `?${q}` : ""}`
    );
  },
  getXeroReferenceTrackingCategories: (params?: {
    search?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<{ items: XeroTrackingCategoryRow[]; total: number }>(
      `/api/integrations/xero/reference/tracking-categories${q ? `?${q}` : ""}`
    );
  },
  getXeroSyncHistory: (params?: { limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroSyncHistoryRow[] }>(
      `/api/integrations/xero/sync-history${q ? `?${q}` : ""}`
    );
  },
  getXeroExportHistory: (params?: { limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<XeroMasterListMeta & { items: XeroExportHistoryRow[] }>(
      `/api/integrations/xero/export-history${q ? `?${q}` : ""}`
    );
  },
  getXeroMasterTotals: () =>
    request<XeroMasterTotals>("/api/integrations/xero/master-totals"),
  reconcileXero: (ref_id?: number) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{
      job_id: number | null;
      reconciled: number;
      failed: number;
      committed: boolean;
    }>("/api/integrations/xero/reconcile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ref_id != null ? { ref_id } : {}),
    });
  },
  validateXeroInvoiceExport: (invoiceId: number) => {
    return request<{
      valid: boolean;
      invoice_id: number;
      blocking_errors: Array<{ field: string; code: string; message: string }>;
      canonical?: Record<string, unknown> | null;
    }>(`/api/integrations/xero/invoices/${invoiceId}/validate`, { method: "POST" });
  },
  exportXeroInvoice: (invoiceId: number) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{
      skipped?: boolean;
      reason?: string;
      evidence: XeroExportLedgerRow;
      attachment?: Record<string, unknown> | null;
    }>(`/api/integrations/xero/invoices/${invoiceId}/export`, { method: "POST" });
  },
  getXeroMappings: () => {
    return request<{ items: XeroMappingRow[] }>("/api/integrations/xero/mappings");
  },
  putXeroMappings: (mappings: Array<Partial<XeroMappingRow> & { mapping_type: string; source_key: string }>) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{ items: XeroMappingRow[] }>("/api/integrations/xero/mappings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mappings }),
    });
  },
  getXeroExportLedger: (params?: { status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return request<{ items: XeroExportLedgerRow[]; total: number }>(
      `/api/integrations/xero/exports${q ? `?${q}` : ""}`
    );
  },
  getXeroExportQueue: (params?: { limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return request<{ items: XeroExportQueueItem[] }>(
      `/api/integrations/xero/export-queue${q ? `?${q}` : ""}`
    );
  },
  refreshXeroExport: (syncId: number) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{ evidence: XeroExportLedgerRow; divergence_flags: string[] }>(
      `/api/integrations/xero/exports/${syncId}/refresh`,
      { method: "POST" }
    );
  },
  retryXeroAttachment: (syncId: number) => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{ evidence: XeroExportLedgerRow }>(
      `/api/integrations/xero/exports/${syncId}/retry-attachment`,
      { method: "POST" }
    );
  },
  runXeroReconciliation: () => {
    bustGetCacheByPrefix("/api/integrations/xero");
    return request<{ checked: number; divergences: Array<Record<string, unknown>> }>(
      "/api/integrations/xero/reconciliation/run",
      { method: "POST" }
    );
  },
  getXeroInvoiceStatus: (invoiceId: number, options?: FreshRequestOptions) => {
    const path = `/api/integrations/xero/invoices/${invoiceId}/status`;
    if (options?.fresh) bustGetCache(path);
    return request<XeroInvoiceStatus>(path);
  },
  getViberStatus: (options?: FreshRequestOptions) => {
    const path = "/api/integrations/viber/status";
    if (options?.fresh) bustGetCache(path);
    return request<ViberStatus>(path);
  },
  connectViber: (auth_token: string) => {
    bustGetCache("/api/integrations/viber/status");
    return request<{ connection: ViberStatus["connections"][number]; bot_name: string | null }>(
      "/api/integrations/viber/connect",
      { method: "POST", body: JSON.stringify({ auth_token }) }
    );
  },
  disconnectViber: (id: number) => {
    bustGetCache("/api/integrations/viber/status");
    return request<{ disconnected: boolean; id: number }>(
      `/api/integrations/viber/disconnect/${id}`,
      { method: "DELETE" }
    );
  },
  testViberConnection: (id: number) => {
    bustGetCache("/api/integrations/viber/status");
    return request<{
      ok: boolean;
      integration_health: string;
      warnings: string[];
      profile: Record<string, unknown>;
    }>(`/api/integrations/viber/test/${id}`, { method: "POST" });
  },

  getNavBadges: () => request<NavBadges>("/api/dashboard/badges"),
  getNotifications: (limit = 30) =>
    request<NotificationsResponse>(`/api/notifications?limit=${limit}`),
  markNotificationsRead: () =>
    request<{ unread_count: number }>("/api/notifications/mark-read", { method: "POST" }),
  getStats: () => request<DashboardStats>("/api/dashboard/stats"),
  getDashboardOverview: (activityLimit = 10, month?: string) => {
    const params = new URLSearchParams({
      activity_limit: String(activityLimit),
    });
    if (month) params.set("month", month);
    return request<DashboardOverview>(`/api/dashboard/overview?${params}`);
  },
  getPositionLiquidity: (period?: DashboardPeriod) =>
    request<PositionLiquidityDashboard>(dashboardApiPath("/api/dashboard/position-liquidity", period)),
  getEfficiencyAutomation: (period?: DashboardPeriod) =>
    request<EfficiencyAutomationDashboard>(
      dashboardApiPath("/api/dashboard/efficiency-automation", period)
    ),
  getCashLiabilityOutlook: (period?: DashboardPeriod) =>
    request<CashLiabilityOutlookDashboard>(
      dashboardApiPath("/api/dashboard/cash-liability-outlook", period)
    ),
  getBudgetConcentrationRisk: (period?: DashboardPeriod) =>
    request<BudgetConcentrationRiskDashboard>(
      dashboardApiPath("/api/dashboard/budget-concentration-risk", period)
    ),
  getCfoAlerts: (period?: DashboardPeriod) =>
    request<CfoAlertsDashboard>(dashboardApiPath("/api/dashboard/cfo-alerts", period)),
  getProcessEfficiencyTrends: (period?: DashboardPeriod) =>
    request<ProcessEfficiencyTrendsDashboard>(
      dashboardApiPath("/api/dashboard/process-efficiency-trends", period)
    ),
  getActivity: (limit = 20) =>
    request<ActivityItem[]>(`/api/dashboard/activity?limit=${limit}`),
  listInvoices: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/invoices${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return request<Invoice[]>(path);
  },
  listInvoicesWithMeta: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/invoices${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<Invoice[]>(path);
  },
  getInvoice: (id: number, options?: FreshRequestOptions) => {
    const q = options?.revealBank ? "?reveal_bank=true" : "";
    const path = `/api/invoices/${id}${q}`;
    if (options?.fresh) bustGetCache(path);
    return request<InvoiceDetails>(path);
  },
  updateInvoice: (id: number, body: InvoiceUpdatePayload) => {
    bustGetCacheByPrefix("/api/invoices");
    bustGetCacheByPrefix("/api/approvals");
    return request<InvoiceDetails>(`/api/invoices/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  getInvoicePipeline: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/pipeline`;
    if (options?.fresh) bustGetCache(path);
    return request<InvoicePipelineResponse>(path).then((r) => ({
      steps: r.steps ?? [],
      active_path: r.active_path ?? "unknown",
    }));
  },
  getInvoiceClassificationAudit: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/classification-audit`;
    if (options?.fresh) bustGetCache(path);
    return request<InvoiceClassificationAudit>(path);
  },
  resolveInvoiceClassification: (
    id: number,
    body: { confirmed_dt: string; reprocess?: boolean }
  ) =>
    request<Invoice>(`/api/invoices/${id}/classification/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getClassificationReviewQueue: (options?: FreshRequestOptions) => {
    const path = "/api/invoices/classification-review";
    if (options?.fresh) bustGetCache(path);
    return request<import("@/api/types").ClassificationReviewItem[]>(path);
  },
  getPurchaseDossier: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/purchase-dossier`;
    if (options?.fresh) bustGetCache(path);
    return request<PurchaseDossier>(path);
  },
  getSalesDossier: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/sales-dossier`;
    if (options?.fresh) bustGetCache(path);
    return request<SalesDossierResponse>(path);
  },
  getMatrixWithMeta: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/matrix${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<MatrixRow[]>(path);
  },
  getMatrixAnalysis: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/matrix/analysis${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<import("@/lib/uploadAnalysisApi").MatrixAnalysisApiResponse>(path);
  },
  listDossiersWithMeta: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/dossiers${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<import("@/lib/dossierApi").DossierSummaryApi[]>(path);
  },
  getDossier: (dossierId: string, options?: FreshRequestOptions) => {
    const path = `/api/dossiers/${encodeURIComponent(dossierId)}`;
    if (options?.fresh) bustGetCache(path);
    return request<import("@/lib/dossierApi").DossierSummaryApi>(path);
  },
  addDossierManualLink: (
    dossierId: string,
    body: { linked_invoice_id: number; slot_id?: string | null }
  ) =>
    request<import("@/lib/dossierApi").DossierSummaryApi>(
      `/api/dossiers/${encodeURIComponent(dossierId)}/manual-links`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  removeDossierManualLink: (dossierId: string, linkId: number) =>
    request<import("@/lib/dossierApi").DossierSummaryApi>(
      `/api/dossiers/${encodeURIComponent(dossierId)}/manual-links/${linkId}`,
      { method: "DELETE" }
    ),
  uploadInvoice: async (
    file: File,
    purchaseDocumentType?: "po" | "grn" | "invoice",
    options?: { deferProcessing?: boolean }
  ): Promise<import("./types").UploadInvoiceResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const params = new URLSearchParams();
    if (purchaseDocumentType != null) {
      params.set("purchase_document_type", purchaseDocumentType);
    }
    if (options?.deferProcessing) {
      params.set("defer_processing", "true");
    }
    const q = params.toString() ? `?${params.toString()}` : "";
    invalidateGetCache();
    const res = await fetch(`${BASE}/api/invoices/upload${q}`, {
      method: "POST",
      body: fd,
      headers: getScopedAuthHeaders(),
    });
    if (!res.ok) {
      const msg = await parseErrorResponse(res);
      if (res.status === 401) {
        void notifyUnauthorized();
      }
      throw new ApiError(msg, res.status);
    }
    const json = (await res.json()) as ApiEnvelope<Invoice>;
    if (json.error) throw new Error(json.error.message);
    const invoice = json.data;
    const segmentCount = json.meta?.segment_count ?? 1;
    const segmentInvoiceIds =
      json.meta?.segment_invoice_ids?.length
        ? json.meta.segment_invoice_ids
        : [invoice.id];
    return { invoice, segmentCount, segmentInvoiceIds };
  },
  processInvoicesBatch: (invoiceIds: number[]) =>
    request<{ queued: number; status: string }>("/api/invoices/process-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invoice_ids: invoiceIds }),
    }),
  reprocess: (id: number) => {
    bustGetCacheByPrefix("/api/invoices");
    bustGetCacheByPrefix("/api/approvals");
    return request<Invoice>(`/api/invoices/${id}/reprocess`, { method: "POST" });
  },
  setTeamExpenseKind: (id: number, teamExpenseKind: string) => {
    bustGetCacheByPrefix("/api/invoices");
    return request<Invoice>(`/api/invoices/${id}/team-expense-kind`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ team_expense_kind: teamExpenseKind }),
    });
  },
  attachInvoiceFile: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Invoice>(`/api/invoices/${id}/attach`, { method: "POST", body: fd });
  },
  previewInvoiceFile: async (id: number) => {
    const { blob, filename } = await requestBlob(
      `/api/invoices/${id}/file`,
      undefined,
      "invoice.pdf"
    );
    const viewBlob = normalizePreviewBlob(blob, filename);
    return {
      url: URL.createObjectURL(viewBlob),
      mimeType: viewBlob.type || "application/octet-stream",
      filename,
    };
  },
  downloadInvoiceFile: async (id: number) => {
    const { blob, filename } = await requestBlob(
      `/api/invoices/${id}/file`,
      undefined,
      "invoice.pdf"
    );
    saveBlobAsFile(blob, filename);
  },
  triggerProcess: (mailboxId?: number) =>
    request<{ task_id: string; status: string }>("/api/process/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mailboxId != null ? { mailbox_id: mailboxId } : {}),
    }),
  getProcessingStatus: () => request<ProcessingStatus>("/api/process/status"),
  listApprovals: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams({ page_size: "100", ...params }).toString();
    const path = `/api/approvals?${q}`;
    if (options?.fresh) bustGetCache(path);
    return request<Invoice[]>(path);
  },
  listApprovalsWithMeta: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams({ page_size: "100", ...params }).toString();
    const path = `/api/approvals?${q}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<Invoice[]>(path);
  },
  listApprovalsBoard: (options?: FreshRequestOptions) => {
    const path = "/api/approvals/board";
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<Invoice[]>(path);
  },
  confirmProcess: (id: number) => {
    bustGetCacheByPrefix("/api/approvals");
    bustGetCacheByPrefix("/api/invoices");
    return request<Invoice>(`/api/invoices/${id}/confirm-process`, { method: "POST" });
  },
  approve: (id: number) => {
    bustGetCacheByPrefix("/api/approvals");
    bustGetCacheByPrefix("/api/invoices");
    return request<Invoice>(`/api/approvals/${id}/approve`, { method: "POST" });
  },
  reject: (id: number) => {
    bustGetCacheByPrefix("/api/approvals");
    bustGetCacheByPrefix("/api/invoices");
    bustGetCacheByPrefix("/api/purchases");
    bustGetCacheByPrefix("/api/sales");
    return request<Invoice>(`/api/approvals/${id}/reject`, { method: "POST" });
  },
  requestApproval: (id: number) =>
    request<Invoice>(`/api/approvals/${id}/request`, { method: "POST" }),
  publishInvoice: (id: number) =>
    request<Invoice>(`/api/invoices/${id}/publish`, { method: "POST" }),
  remapInvoices: () =>
    request<{ updated: number; invoice_ids?: number[] }>("/api/invoices/remap", {
      method: "POST",
    }),
  listAuditLog: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/audit-log${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return request<AuditLogEntry[]>(path);
  },
  getApprovalPolicy: () => request<ApprovalPolicy>("/api/approval-policy"),
  putApprovalPolicy: (body: ApprovalPolicy) =>
    request<ApprovalPolicy>("/api/approval-policy", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  unlockApprovalPolicy: (code: string) =>
    request<ApprovalPolicy>("/api/approval-policy/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }),
  deleteApprovalPermanently: (id: number) => {
    bustGetCacheByPrefix("/api/approvals");
    bustGetCacheByPrefix("/api/invoices");
    bustGetCacheByPrefix("/api/purchases");
    bustGetCacheByPrefix("/api/sales");
    return request<void>(`/api/approvals/${id}`, { method: "DELETE" });
  },
  listVendors: (options?: FreshRequestOptions) => {
    const path = "/api/vendors";
    if (options?.fresh) bustGetCache(path);
    return request<Vendor[]>(path);
  },
  listVendorActivity: (options?: FreshRequestOptions) => {
    const path = "/api/vendors/activity";
    if (options?.fresh) bustGetCache(path);
    return request<VendorActivity[]>(path);
  },
  createVendor: (body: Omit<Vendor, "id">) =>
    request<Vendor>("/api/vendors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateVendor: (id: number, body: Partial<Vendor>) =>
    request<Vendor>(`/api/vendors/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteVendor: (id: number) =>
    request<void>(`/api/vendors/${id}`, { method: "DELETE" }),
  listVendorPayoutMethods: (vendorId: number, options?: FreshRequestOptions) => {
    const path = `/api/vendors/${vendorId}/payout-methods`;
    if (options?.fresh) bustGetCache(path);
    return request<VendorPayoutMethod[]>(path);
  },
  createVendorPayoutMethod: (vendorId: number, body: VendorPayoutMethodCreate) =>
    request<VendorPayoutMethod>(`/api/vendors/${vendorId}/payout-methods`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateVendorPayoutMethod: (
    vendorId: number,
    methodId: number,
    body: VendorPayoutMethodUpdate
  ) =>
    request<VendorPayoutMethod>(`/api/vendors/${vendorId}/payout-methods/${methodId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteVendorPayoutMethod: (vendorId: number, methodId: number) =>
    request<void>(`/api/vendors/${vendorId}/payout-methods/${methodId}`, {
      method: "DELETE",
    }),
  listVendorMasters: (options?: FreshRequestOptions) => {
    const q = options?.revealBank ? "?reveal_bank=true" : "";
    const path = `/api/vendor-masters${q}`;
    if (options?.fresh) bustGetCache(path);
    return request<Array<Record<string, unknown>>>(path);
  },
  createVendorMaster: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/vendor-masters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateVendorMaster: (masterId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/vendor-masters/${encodeURIComponent(masterId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteVendorMaster: (masterId: string) =>
    request<void>(`/api/vendor-masters/${encodeURIComponent(masterId)}`, { method: "DELETE" }),
  sendVendorMasterConfirmation: (masterId: string) =>
    request<{ sent: boolean; email?: string | null; error?: string | null; expires_at?: string | null }>(
      `/api/vendor-masters/${encodeURIComponent(masterId)}/send-confirmation`,
      { method: "POST" }
    ),
  listEmployeeMasters: (options?: FreshRequestOptions) => {
    const q = options?.revealBank ? "?reveal_bank=true" : "";
    const path = `/api/employee-masters${q}`;
    if (options?.fresh) bustGetCache(path);
    return request<Array<Record<string, unknown>>>(path);
  },
  createEmployeeMaster: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/employee-masters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateEmployeeMaster: (masterId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/employee-masters/${encodeURIComponent(masterId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteEmployeeMaster: (masterId: string) =>
    request<void>(`/api/employee-masters/${encodeURIComponent(masterId)}`, { method: "DELETE" }),
  sendEmployeeMasterConfirmation: (masterId: string) =>
    request<{ sent: boolean; email?: string | null; error?: string | null; expires_at?: string | null }>(
      `/api/employee-masters/${encodeURIComponent(masterId)}/send-confirmation`,
      { method: "POST" }
    ),
  listDepartmentBudgets: (department?: string) => {
    const q = department?.trim()
      ? `?department=${encodeURIComponent(department.trim())}`
      : "";
    return request<DepartmentBudgetRow[]>(`/api/department-budgets${q}`);
  },
  createDepartmentBudget: (body: {
    gl_ledger: string;
    period_kind: "monthly" | "quarterly" | "annual";
    period_key: string;
    allocated: number;
    department?: string;
    notes?: string | null;
  }) =>
    request<DepartmentBudgetRow>("/api/department-budgets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  upsertParentGlBudgetTree: (body: {
    parent_gl: string;
    period_kind: "monthly" | "quarterly" | "annual";
    period_key: string;
    allocated: number;
    sub_allocations: { gl_ledger: string; allocated: number }[];
    enforcement?: "soft" | "hard";
    notes?: string | null;
  }) =>
    request<DepartmentBudgetRow[]>("/api/department-budgets/tree", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteParentGlBudgetTree: (params: {
    parent_gl: string;
    period_kind: "monthly" | "quarterly" | "annual";
    period_key: string;
  }) => {
    const q = new URLSearchParams({
      parent_gl: params.parent_gl,
      period_kind: params.period_kind,
      period_key: params.period_key,
    });
    return request<void>(`/api/department-budgets/tree?${q}`, { method: "DELETE" });
  },
  updateDepartmentBudget: (
    budgetId: number,
    body: Partial<{
      department: string;
      gl_ledger: string;
      period_kind: "monthly" | "quarterly" | "annual";
      period_key: string;
      allocated: number;
      notes: string | null;
    }>
  ) =>
    request<DepartmentBudgetRow>(`/api/department-budgets/${budgetId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteDepartmentBudget: (budgetId: number) =>
    request<void>(`/api/department-budgets/${budgetId}`, { method: "DELETE" }),
  downloadDepartmentBudgetImportTemplate: async (params?: {
    period_kind?: "monthly" | "quarterly" | "annual";
    period_key?: string;
    prefill_coa?: boolean;
  }) => {
    const q = new URLSearchParams();
    if (params?.period_kind) q.set("period_kind", params.period_kind);
    if (params?.period_key?.trim()) q.set("period_key", params.period_key.trim());
    if (params?.prefill_coa === false) q.set("prefill_coa", "false");
    const qs = q.toString();
    const { blob, filename } = await requestBlob(
      `/api/department-budgets/import/template${qs ? `?${qs}` : ""}`,
      undefined,
      "gl-budget-template.xlsx"
    );
    saveBlobAsFile(blob, filename);
  },
  importDepartmentBudgets: (file: File, dryRun: boolean) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<DepartmentBudgetImportResult>(
      `/api/department-budgets/import?dry_run=${dryRun ? "true" : "false"}`,
      { method: "POST", body: fd }
    );
  },
  downloadEmployeeImportTemplate: async (mode: EmployeeImportMode) => {
    const { blob, filename } = await requestBlob(
      `/api/employee-masters/import/templates/${mode}`,
      undefined,
      `employee-${mode}-template.xlsx`
    );
    saveBlobAsFile(blob, filename);
  },
  importEmployeeMasters: (mode: EmployeeImportMode, file: File, dryRun: boolean) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<EmployeeImportResult>(
      `/api/employee-masters/import?mode=${encodeURIComponent(mode)}&dry_run=${dryRun ? "true" : "false"}`,
      { method: "POST", body: fd }
    );
  },
  listPendingVendors: (options?: FreshRequestOptions) => {
    const path = "/api/pending-vendors";
    if (options?.fresh) bustGetCache(path);
    return request<Array<Record<string, unknown>>>(path);
  },
  createPendingVendor: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/pending-vendors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  promotePendingVendor: (pendingId: number, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/pending-vendors/${pendingId}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  dismissPendingVendor: (pendingId: number) =>
    request<void>(`/api/pending-vendors/${pendingId}/dismiss`, { method: "POST" }),
  listPendingCustomers: (options?: FreshRequestOptions) => {
    const path = "/api/pending-customers";
    if (options?.fresh) bustGetCache(path);
    return request<Array<Record<string, unknown>>>(path);
  },
  createPendingCustomer: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/pending-customers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  promotePendingCustomer: (pendingId: number, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/pending-customers/${pendingId}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  dismissPendingCustomer: (pendingId: number) =>
    request<void>(`/api/pending-customers/${pendingId}/dismiss`, { method: "POST" }),
  getRuleBookConfig: (params?: { fields?: string }) => {
    const q = params?.fields ? `?fields=${encodeURIComponent(params.fields)}` : "";
    return request<RuleBookConfig>(`/api/rule-book/config${q}`);
  },
  getAiProviders: () =>
    request<import("@/api/types").AiProvidersResponse>("/api/rule-book/ai-providers"),
  getRecognitionSignalCatalog: () =>
    request<{
      weak_signal_ids: string[];
      pick_groups: string[][];
      supporting_guards: Array<Record<string, unknown>>;
      signals: Array<{
        id: string;
        label: string;
        hint: string;
        channel: string;
        strength: string;
        example: string;
        condition: { field: string; operator: string; value: string };
      }>;
      playbook_recommended_identity: Record<string, string[]>;
    }>("/api/rule-book/recognition-signals"),
  testDocumentTypeRecognition: (body: import("@/api/types").DocumentTypeRecognitionTestRequest) =>
    request<import("@/api/types").DocumentTypeRecognitionTestResponse>(
      "/api/rule-book/document-types/test-recognition",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  getVaultTree: (options?: FreshRequestOptions & { includeFiles?: boolean; fileLimit?: number }) => {
    const qs = new URLSearchParams();
    if (options?.includeFiles === false) qs.set("include_files", "false");
    if (options?.fileLimit != null) qs.set("file_limit", String(options.fileLimit));
    const query = qs.toString();
    const path = `/api/vault/tree${query ? `?${query}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return request<VaultTreeResponse>(path);
  },
  getVaultFiles: (
    params?: {
      invoiceId?: number;
      org?: string;
      book?: string;
      documentType?: string;
      vendor?: string;
      year?: string;
      month?: string;
      poFolder?: string;
      limit?: number;
    },
    options?: FreshRequestOptions
  ) => {
    const qs = new URLSearchParams();
    if (params?.invoiceId != null) qs.set("invoice_id", String(params.invoiceId));
    if (params?.org) qs.set("org", params.org);
    if (params?.book) qs.set("book", params.book);
    if (params?.documentType) qs.set("document_type", params.documentType);
    if (params?.vendor) qs.set("vendor", params.vendor);
    if (params?.year) qs.set("year", params.year);
    if (params?.month) qs.set("month", params.month);
    if (params?.poFolder) qs.set("po_folder", params.poFolder);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    const query = qs.toString();
    const path = `/api/vault/files${query ? `?${query}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return request<VaultFilesResponse>(path);
  },
  getVaultDocumentSets: (options?: FreshRequestOptions) => {
    const path = "/api/vault/document-sets";
    if (options?.fresh) bustGetCache(path);
    return request<VaultDocumentSetsResponse>(path);
  },
  migrateVault: () =>
    request<VaultMigrateResponse>("/api/vault/migrate", { method: "POST" }),
  putRuleBookConfig: (body: RuleBookRulesPayload) =>
    request<RuleBookConfig>("/api/rule-book/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  putRuleBookVendorDetection: (config: RuleBookConfig["vendor_detection_config"]) =>
    request<Pick<RuleBookConfig, "vendor_detection_config">>(
      "/api/rule-book/config/vendor-detection",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor_detection_config: config }),
      }
    ),
  getEmailIngestionRules: () =>
    request<
      Pick<RuleBookConfig, "email_capture_rules"> & {
        rule_warnings?: Record<string, string[]>;
      }
    >("/api/mailboxes/ingestion-rules"),
  putEmailIngestionRules: (rules: RuleBookConfig["email_capture_rules"]) =>
    request<
      Pick<RuleBookConfig, "email_capture_rules"> & {
        warnings?: string[];
        rule_warnings?: Record<string, string[]>;
      }
    >(
      "/api/mailboxes/ingestion-rules",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email_capture_rules: rules }),
      }
    ),
  getEmailIngestionRecentSkips: (mailbox: string) =>
    request<{
      mailbox: string;
      skips: Array<{
        sender: string;
        subject: string;
        attachment: string;
        reason: string;
        reason_label: string;
        timestamp: string | null;
        relative_time: string;
        capture_rule_id?: string | null;
        capture_rule_name?: string | null;
        message_id?: string | null;
      }>;
    }>(`/api/mailboxes/ingestion-rules/recent-skips?mailbox=${encodeURIComponent(mailbox)}`),
  getEmailIngestionStats: () =>
    request<{
      ingest_stats: Record<string, { matched_count: number; last_matched: string }>;
    }>("/api/mailboxes/ingestion-rules/stats"),
  testEmailIngestionRule: (body: {
    mailbox: string;
    root: Record<string, unknown>;
    lookback_days?: number;
    rule_name?: string;
  }) =>
    request<{
      mailbox: string;
      lookback_days: number;
      message_count: number;
      matches: Array<{
        message_id: string;
        subject: string;
        sender: string;
        attachment: string;
        received_at: string | null;
      }>;
      warnings: string[];
    }>("/api/mailboxes/ingestion-rules/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  putRuleBookBankFileSettings: (settings: BankFileSettings) =>
    request<Pick<RuleBookConfig, "bank_file_settings">>(
      "/api/rule-book/config/bank-file-settings",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bank_file_settings: settings }),
      }
    ),
  deleteRuleBookDocumentType: (code: string) =>
    request<RuleBookConfig>(
      `/api/rule-book/document-types/${encodeURIComponent(code.trim())}`,
      { method: "DELETE" }
    ),
  getRuleBookChangelog: (limit = 20) =>
    request<RuleBookChangelogEntry[]>(`/api/rule-book/changelog?limit=${limit}`),
  getSettings: () => request<AppSettings>("/api/settings"),
  getRegistryFields: () => request<RegistryFieldsResponse>("/api/registry/fields"),
  listReconciliation: () => request<DailyReconciliation[]>("/api/reconciliation/daily"),
  getReconciliationDayDetail: (reconDate: string) =>
    request<ReconciliationDayDetail>(`/api/reconciliation/daily/${reconDate}/detail`),
  getReconciliationOverview: () =>
    request<ReconciliationOverview>("/api/reconciliation/overview"),
  getLedgerLink: (options?: FreshRequestOptions & { fields?: "overview" | "exports" }) => {
    const path = options?.fields ? `/api/ledger-link?fields=${options.fields}` : "/api/ledger-link";
    if (options?.fresh) bustGetCache(path);
    return request<LedgerLinkResponse>(path);
  },
  getLedgerLinkExports: (options?: FreshRequestOptions & { limit?: number }) => {
    const params = new URLSearchParams();
    if (options?.limit != null) params.set("limit", String(options.limit));
    const qs = params.toString();
    const path = qs ? `/api/ledger-link/exports?${qs}` : "/api/ledger-link/exports";
    if (options?.fresh) bustGetCache(path);
    return request<LedgerLinkExports>(path);
  },
  getLedgerLinkDay: (day: string, options?: FreshRequestOptions) => {
    const path = `/api/ledger-link/days/${day}`;
    if (options?.fresh) bustGetCache(path);
    return request<ReconDayOverviewRow>(path);
  },
  getBilling: (options?: FreshRequestOptions) => {
    const path = "/api/billing";
    if (options?.fresh) bustGetCache(path);
    return request<BillingState>(path);
  },
  getGeoCountry: () => request<{ country_code: string | null }>("/api/geo/country"),
  getBillingUsage: (
    page = 1,
    pageSize = 50,
    category?: BillingLedgerCategory,
    options?: FreshRequestOptions
  ) => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (category) query.set("category", category);
    const path = `/api/billing/usage?${query.toString()}`;
    if (options?.fresh) bustGetCache(path);
    return request<BillingUsageHistory>(path);
  },
  topUpBilling: (amount: number) =>
    request<BillingState>("/api/billing/top-up", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    }),
  upgradeBillingPlan: () =>
    request<BillingState | CheckoutSessionResult>("/api/billing/upgrade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: "studio" }),
    }),
  createTopUpCheckout: (amount: number) =>
    request<CheckoutSessionResult>("/api/billing/topup/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    }),
  getCheckoutStatus: (sessionId: string) =>
    request<CheckoutStatusResult>(`/api/billing/checkout/status/${encodeURIComponent(sessionId)}`),
  createSignupCheckout: (body: BillingSignupCheckoutBody) =>
    request<CheckoutSessionResult>("/api/billing/signup/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getPublicBillingPlans: (country: string) =>
    request<BillingPlansCatalog>(
      `/api/billing/plans?country=${encodeURIComponent(country)}`
    ),
  getSignupCheckoutStatus: (sessionId: string) =>
    request<CheckoutStatusResult>(
      `/api/billing/signup/status/${encodeURIComponent(sessionId)}`
    ),
  getPlatformCreditSettings: () =>
    request<PlatformCreditSettings>("/api/platform/credit-settings"),
  updatePlatformCreditSettings: (body: Partial<PlatformCreditSettings>) =>
    request<PlatformCreditSettings>("/api/platform/credit-settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getPlatformPrompts: () => request<PlatformPromptSummary[]>("/api/platform/prompts"),
  getPlatformPrompt: (key: string) =>
    request<PlatformPromptSummary>(`/api/platform/prompts/${encodeURIComponent(key)}`),
  getPlatformPromptVersions: (key: string) =>
    request<PlatformPromptVersionList>(
      `/api/platform/prompts/${encodeURIComponent(key)}/versions`
    ),
  createPlatformPromptVersion: (
    key: string,
    body: { body: string; notes?: string }
  ) =>
    request<PlatformPromptSummary>(
      `/api/platform/prompts/${encodeURIComponent(key)}/versions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  activatePlatformPromptVersion: (key: string, version: number) =>
    request<PlatformPromptSummary>(
      `/api/platform/prompts/${encodeURIComponent(key)}/versions/${version}/activate`,
      { method: "POST" }
    ),
  getPlatformTenantUsage: (tenantId: string, page = 1, pageSize = 50) =>
    request<BillingUsageHistory>(
      `/api/platform/tenants/${tenantId}/usage?page=${page}&page_size=${pageSize}`
    ),
  updatePlatformTenantBilling: (
    tenantId: string,
    body: {
      plan?: string;
      enterprise_monthly_credits?: number;
      credits_per_page_override?: number;
      grant_credits?: number;
    }
  ) =>
    request<PlatformTenantDetail>(`/api/platform/tenants/${tenantId}/billing`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getReportsAnalytics: (month: string) =>
    request<ReportsAnalytics>(`/api/reports/analytics?month=${encodeURIComponent(month)}`),
  getReportCatalog: () => request<ReportCatalogResponse>("/api/reports/catalog"),
  putReportFavourites: (reportIds: string[]) =>
    request<string[]>("/api/reports/favourites", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_ids: reportIds }),
    }),
  getReportPreview: (
    reportId: string,
    params: {
      range: string;
      compare?: boolean;
      from?: string;
      to?: string;
    }
  ) => {
    const q = new URLSearchParams();
    q.set("range", params.range);
    if (params.compare) q.set("compare", "true");
    if (params.from) q.set("from", params.from);
    if (params.to) q.set("to", params.to);
    return request<ReportPreview>(
      `/api/reports/${encodeURIComponent(reportId)}/preview?${q.toString()}`
    );
  },
  listReportLayouts: (reportId: string) =>
    request<ReportColumnLayoutItem[]>(
      `/api/reports/${encodeURIComponent(reportId)}/layouts`
    ),
  createReportLayout: (reportId: string, body: ReportColumnLayoutCreate) =>
    request<ReportColumnLayoutItem>(
      `/api/reports/${encodeURIComponent(reportId)}/layouts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  updateReportLayout: (
    reportId: string,
    layoutId: number,
    body: ReportColumnLayoutUpdate
  ) =>
    request<ReportColumnLayoutItem>(
      `/api/reports/${encodeURIComponent(reportId)}/layouts/${layoutId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  setDefaultReportLayout: (reportId: string, layoutId: number) =>
    request<ReportColumnLayoutItem>(
      `/api/reports/${encodeURIComponent(reportId)}/layouts/${layoutId}/default`,
      { method: "POST" }
    ),
  deleteReportLayout: (reportId: string, layoutId: number) =>
    request<null>(
      `/api/reports/${encodeURIComponent(reportId)}/layouts/${layoutId}`,
      { method: "DELETE" }
    ),
  exportReport: async (reportId: string, body: ReportExportRequest) => {
    const fallback = `${reportId}.${body.format === "pdf" ? "pdf" : "xlsx"}`;
    const { blob, filename } = await requestBlob(
      `/api/reports/${encodeURIComponent(reportId)}/export`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      fallback
    );
    saveBlobAsFile(blob, filename);
    return { filename };
  },
  getApBalances: (asOf?: string) => {
    const params = new URLSearchParams();
    if (asOf) params.set("as_of", asOf);
    const query = params.toString();
    return request<SubledgerBalancesResponse>(
      `/api/reports/subledger/ap-balances${query ? `?${query}` : ""}`
    );
  },
  getArBalances: (asOf?: string) => {
    const params = new URLSearchParams();
    if (asOf) params.set("as_of", asOf);
    const query = params.toString();
    return request<SubledgerBalancesResponse>(
      `/api/reports/subledger/ar-balances${query ? `?${query}` : ""}`
    );
  },
  getReportDocuments: (filter?: ReportDateFilter) =>
    request<ReportDocumentRow[]>(`/api/reports/documents${reportDateQuery(filter)}`),
  getTeamExpenseAdvanceSettlement: () =>
    request<EmployeeAdvanceSettlementRow[]>(
      "/api/reports/team-expenses/advance-settlement"
    ),
  getTeamExpenseBudgetUtilization: () =>
    request<EmployeeBudgetUtilizationRow[]>(
      "/api/reports/team-expenses/budget-utilization"
    ),
  getTeamExpenseDepartmentBudgetUtilization: () =>
    request<DepartmentBudgetUtilizationRow[]>(
      "/api/reports/team-expenses/department-budget-utilization"
    ),
  getTeamExpenseWorkspaceKpis: () =>
    request<import("@/api/types").TeamExpenseWorkspaceKpis>(
      "/api/reports/team-expenses/workspace-kpis"
    ),
  getExpensesWorkspaceKpis: () =>
    request<import("@/api/types").TeamExpenseWorkspaceKpis>(
      "/api/reports/expenses/workspace-kpis"
    ),
  getTeamExpenseExpenseSummary: (filter?: ReportDateFilter) =>
    request<EmployeeExpenseSummaryRow[]>(
      `/api/reports/team-expenses/expense-summary${reportDateQuery(filter)}`
    ),
  getTeamExpenseEmployeeSpendDetail: () =>
    request<EmployeeSpendDetailRow[]>(
      "/api/reports/team-expenses/employee-spend-detail"
    ),
  getTeamExpenseEmployeeAdvanceDetail: () =>
    request<EmployeeAdvanceDetailRow[]>(
      "/api/reports/team-expenses/employee-advance-detail"
    ),
  downloadTeamExpenseReport: async (
    report:
      | "budget-utilization"
      | "department-budget-utilization"
      | "expense-summary"
      | "employee-spend-detail"
      | "employee-advance-detail",
    filter?: ReportDateFilter
  ) => {
    const { blob, filename, headers } = await requestBlob(
      `/api/reports/team-expenses/${report}/export${reportDateQuery(filter)}`,
      undefined,
      `te_${report.replace(/-/g, "_")}.xlsx`
    );
    const parsedRows = Number(headers.get("X-Data-Rows") ?? "");
    const dataRows = Number.isFinite(parsedRows) && parsedRows >= 0 ? parsedRows : 0;
    saveBlobAsFile(
      new Blob([blob], {
        type:
          blob.type ||
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
      filename
    );
    return { dataRows };
  },
  generateReport: (filter?: ReportDateFilter) =>
    request<{ path: string; filename: string }>(
      `/api/reports/generate${reportDateQuery(filter)}`,
      { method: "POST" }
    ),
  downloadReport: async (filter?: ReportDateFilter, suggestedFilename?: string) => {
    const fallback = suggestedFilename || defaultReportFilename(filter);
    const { blob, filename } = await requestBlob(
      `/api/reports/download${reportDateQuery(filter)}`,
      undefined,
      fallback
    );
    saveBlobAsFile(blob, filename);
  },
  downloadAuditLogCsv: async (filter?: ReportDateFilter) => {
    const params = new URLSearchParams({
      document_only: "true",
      dedupe: "true",
    });
    if (filter?.dateFrom) params.set("date_from", filter.dateFrom);
    if (filter?.dateTo) params.set("date_to", filter.dateTo);
    const { blob, filename } = await requestBlob(
      `/api/audit-log/export?${params.toString()}`,
      undefined,
      defaultAuditLogFilename(filter)
    );
    saveBlobAsFile(blob, filename);
  },
  downloadDocumentsBundle: async (
    filter?: ReportDateFilter,
    options?: { format?: "excel" | "plain" }
  ) => {
    const params = new URLSearchParams();
    if (filter?.dateFrom) params.set("date_from", filter.dateFrom);
    if (filter?.dateTo) params.set("date_to", filter.dateTo);
    if (options?.format) {
      params.set("format", options.format);
    }
    try {
      const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (browserTz) params.set("tz", browserTz);
    } catch {
      /* keep UTC on the server when Intl is unavailable */
    }
    const query = params.toString();
    const { blob, filename, headers } = await requestBlob(
      `/api/reports/documents-bundle/export${query ? `?${query}` : ""}`,
      undefined,
      defaultDocumentsBundleFilename(filter)
    );
    const parsedRows = Number(headers.get("X-Data-Rows") ?? "");
    const dataRows = Number.isFinite(parsedRows) && parsedRows >= 0 ? parsedRows : 0;
    saveBlobAsFile(
      new Blob([blob], {
        type:
          blob.type ||
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
      filename
    );
    return { dataRows };
  },
  listPurchases: (options?: FreshRequestOptions) => {
    const path = "/api/purchases";
    if (options?.fresh) bustGetCache(path);
    return request<PurchaseOrderApi[]>(path);
  },
  listPurchasesTwoWay: (options?: FreshRequestOptions) => {
    const path = "/api/purchases/two-way";
    if (options?.fresh) bustGetCache(path);
    return request<PurchaseOrderApi[]>(path);
  },
  getPurchaseWorkspaceKpis: (options?: FreshRequestOptions) => {
    const path = "/api/purchases/kpis";
    if (options?.fresh) bustGetCache(path);
    return request<PurchaseWorkspaceKpis>(path);
  },
  approvePurchaseVariance: (purchaseOrderId: number) =>
    request<PurchaseOrderApi>(`/api/purchases/${purchaseOrderId}/approve-variance`, {
      method: "POST",
    }),
  recordGoodsReceipt: (
    purchaseOrderId: number,
    body: { grn_qty: number; grn_date?: string; receiver?: string; condition_note?: string }
  ) =>
    request<PurchaseOrderApi>(`/api/purchases/${purchaseOrderId}/grn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listSales: (options?: FreshRequestOptions) => {
    const path = "/api/sales";
    if (options?.fresh) bustGetCache(path);
    return request<SalesOrderApi[]>(path);
  },
  getSalesWorkspaceKpis: (options?: FreshRequestOptions) => {
    const path = "/api/sales/kpis";
    if (options?.fresh) bustGetCache(path);
    return request<SalesWorkspaceKpis>(path);
  },
  listSalesTwoWay: (options?: FreshRequestOptions) => {
    const path = "/api/sales/two-way";
    if (options?.fresh) bustGetCache(path);
    return request<import("@/api/types").TwoWaySalesListApi>(path);
  },
  approveSalesVariance: (salesOrderId: number) =>
    request<SalesOrderApi>(`/api/sales/${salesOrderId}/approve-variance`, {
      method: "POST",
    }),
  recordDeliveryNote: (
    salesOrderId: number,
    body: { dn_qty: number; dn_date?: string; shipper?: string; condition_note?: string }
  ) =>
    request<SalesOrderApi>(`/api/sales/${salesOrderId}/dn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  fetchSalesDossier: (invoiceId: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${invoiceId}/sales-dossier`;
    if (options?.fresh) bustGetCache(path);
    return request<SalesDossierResponse>(path);
  },
  listCollections: (
    options?: FreshRequestOptions & { status?: string; limit?: number }
  ) => {
    const params = new URLSearchParams();
    if (options?.status) params.set("status", options.status);
    if (options?.limit != null) params.set("limit", String(options.limit));
    const qs = params.toString();
    const path = qs ? `/api/collections?${qs}` : "/api/collections";
    if (options?.fresh) bustGetCache(path);
    return request<CollectionApi[]>(path);
  },
  getCollectionWorkspaceKpis: (options?: FreshRequestOptions) => {
    const path = "/api/collections/kpis";
    if (options?.fresh) bustGetCache(path);
    return request<CollectionWorkspaceKpis>(path);
  },
  markCollectionReceived: (collectionId: number, body?: CollectionMarkReceivedPayload) => {
    bustGetCacheByPrefix("/api/collections");
    return request<CollectionApi>(`/api/collections/${collectionId}/mark-received`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  },
  listCustomers: (options?: FreshRequestOptions) => {
    const path = "/api/customers";
    if (options?.fresh) bustGetCache(path);
    return request<Customer[]>(path);
  },
  createCustomer: (body: Omit<Customer, "id" | "created_at">) =>
    request<Customer>("/api/customers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateCustomer: (id: number, body: Partial<Customer>) =>
    request<Customer>(`/api/customers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteCustomer: (id: number) =>
    request<void>(`/api/customers/${id}`, { method: "DELETE" }),
  listCustomerMasters: (options?: FreshRequestOptions) => {
    const path = "/api/customer-masters";
    if (options?.fresh) bustGetCache(path);
    return request<Array<Record<string, unknown>>>(path);
  },
  createCustomerMaster: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/customer-masters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateCustomerMaster: (masterId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/customer-masters/${encodeURIComponent(masterId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteCustomerMaster: (masterId: string) =>
    request<void>(`/api/customer-masters/${encodeURIComponent(masterId)}`, { method: "DELETE" }),
  getWalletSummary: (options?: FreshRequestOptions) => {
    const path = "/api/payments/wallet-summary";
    if (options?.fresh) bustGetCache(path);
    return request<WalletSummary>(path);
  },
  listPayments: (
    status?: string,
    options?: FreshRequestOptions & { limit?: number }
  ) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (options?.limit != null) params.set("limit", String(options.limit));
    const qs = params.toString();
    const path = qs ? `/api/payments?${qs}` : "/api/payments";
    if (options?.fresh) bustGetCache(path);
    return request<PaymentApi[]>(path);
  },
  getPaymentWorkspaceKpis: (options?: FreshRequestOptions) => {
    const path = "/api/payments/kpis";
    if (options?.fresh) bustGetCache(path);
    return request<PaymentWorkspaceKpis>(path);
  },
  updatePayment: (
    paymentId: number,
    body: {
      status: string;
      scheduled_date?: string;
      payment_intent?: string;
      failure_reason?: string;
    }
  ) =>
    request<PaymentApi>(`/api/payments/${paymentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getStripeAccount: (options?: FreshRequestOptions) => {
    const path = "/api/payments/stripe/account";
    if (options?.fresh) bustGetCache(path);
    return request<StripeAccount>(path);
  },
  refreshStripeAccount: () =>
    request<StripeAccount>("/api/payments/stripe/account/refresh", {
      method: "POST",
    }),
  connectStripe: () =>
    request<StripeConnectResponse>("/api/payments/stripe/connect", {
      method: "POST",
    }),
  getStripeOnboardingLink: () =>
    request<StripeOnboardingLinkResponse>("/api/payments/stripe/onboarding-link"),
  getStripeOAuthUrl: () =>
    request<StripeOAuthUrlResponse>("/api/payments/stripe/oauth-url"),
  deleteStripeAccount: () =>
    request<StripeDisconnectResponse>("/api/payments/stripe/account", {
      method: "DELETE",
    }),
  getStripeReadiness: (options?: FreshRequestOptions) => {
    const path = "/api/payments/stripe/readiness";
    if (options?.fresh) bustGetCache(path);
    return request<StripeReadinessResponse>(path);
  },
  getStripeGlobalPayoutsReadiness: (options?: FreshRequestOptions) => {
    const path = "/api/payments/stripe/global-payouts/readiness";
    if (options?.fresh) bustGetCache(path);
    return request<StripeGlobalPayoutsReadinessResponse>(path);
  },
  getStripeBalance: (options?: FreshRequestOptions) => {
    const path = "/api/payments/stripe/balance";
    if (options?.fresh) bustGetCache(path);
    return request<StripeBalanceResponse>(path);
  },
  listStripeTransactions: (limit = 20, options?: FreshRequestOptions) => {
    const path = `/api/payments/stripe/transactions?limit=${encodeURIComponent(String(limit))}`;
    if (options?.fresh) bustGetCache(path);
    return request<StripeTransaction[]>(path);
  },
  connectPaypal: () =>
    request<PaypalConnectResponse>("/api/payments/paypal/connect", {
      method: "POST",
    }),
  getPaypalReadiness: (options?: FreshRequestOptions) => {
    const path = "/api/payments/paypal/readiness";
    if (options?.fresh) bustGetCache(path);
    return request<PaypalReadinessResponse>(path);
  },
  disconnectPaypal: () =>
    request<PaypalDisconnectResponse>("/api/payments/paypal/disconnect", {
      method: "POST",
    }),
  getPaypalBalance: (options?: FreshRequestOptions) => {
    const path = "/api/payments/paypal/balance";
    if (options?.fresh) bustGetCache(path);
    return request<PaypalBalanceResponse>(path);
  },
  listPaypalTransactions: (limit = 20, options?: FreshRequestOptions) => {
    const path = `/api/payments/paypal/transactions?limit=${encodeURIComponent(String(limit))}`;
    if (options?.fresh) bustGetCache(path);
    return request<PaypalTransactionsResponse>(path);
  },
  createPaypalPayout: (body: PaypalPayoutRequest) => {
    bustGetCacheByPrefix("/api/payments");
    return request<PaypalPayoutAttempt>("/api/payments/paypal/payouts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  refreshPaypalPayout: (attemptId: number) => {
    bustGetCacheByPrefix("/api/payments");
    return request<PaypalPayoutAttempt>(
      `/api/payments/paypal/payouts/${attemptId}/refresh`,
      { method: "POST" }
    );
  },
  validatePaymentExecutionReadiness: (paymentId: number) =>
    request<PaymentExecutionReadinessResponse>(
      `/api/payments/${paymentId}/execution-readiness`,
      { method: "POST" }
    ),
  approvePayment: (paymentId: number) => {
    bustGetCacheByPrefix("/api/payments");
    return request<PaymentApi>(`/api/payments/${paymentId}/approve`, { method: "POST" });
  },
  createPaymentExecutionInstruction: (paymentId: number) => {
    bustGetCacheByPrefix("/api/payments");
    return request<PaymentExecutionInstructionApi>(
      `/api/payments/${paymentId}/execution-instruction`,
      { method: "POST" }
    );
  },
  exportPaymentExecutionInstruction: (paymentId: number) =>
    request<PaymentExecutionInstructionExportApi>(
      `/api/payments/${paymentId}/execution-instruction/export`
    ),
  markPaymentPaidManual: (paymentId: number, body: PaymentMarkPaidManualPayload) => {
    bustGetCacheByPrefix("/api/payments");
    return request<PaymentApi>(`/api/payments/${paymentId}/mark-paid-manual`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  downloadBatchPaymentBankFile: async (paymentIds: number[]) => {
    const { blob, filename } = await requestBlob(
      "/api/payments/batch/bank-file",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payment_ids: paymentIds }),
      },
      "batch_payment_file.txt"
    );
    bustGetCacheByPrefix("/api/payments");
    saveBlobAsFile(blob, filename);
    return { filename };
  },

  listBankAccounts: (includeArchived = false, options?: FreshRequestOptions) => {
    const path = `/api/bank-feeds/accounts?include_archived=${includeArchived ? "true" : "false"}`;
    if (options?.fresh) bustGetCache(path);
    return request<BankAccount[]>(path);
  },
  createBankAccount: (body: {
    name: string;
    currency: string;
    account_mask?: string | null;
    coa_account_name?: string | null;
  }) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankAccount>("/api/bank-feeds/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  importBankFeedStatement: async (accountId: number, file: File): Promise<BankFeedImport> => {
    const fd = new FormData();
    fd.append("file", file);
    bustGetCacheByPrefix("/api/bank-feeds");
    const res = await fetch(
      `${BASE}/api/bank-feeds/accounts/${accountId}/imports`,
      {
        method: "POST",
        body: fd,
        headers: getScopedAuthHeaders(),
      }
    );
    if (!res.ok) {
      const msg = await parseErrorResponse(res);
      if (res.status === 401) {
        void notifyUnauthorized();
      }
      throw new ApiError(msg, res.status);
    }
    const json = (await res.json()) as ApiEnvelope<BankFeedImport>;
    if (json.error) throw new Error(json.error.message);
    return json.data;
  },
  importBankFeedCsv: async (accountId: number, file: File): Promise<BankFeedImport> =>
    api.importBankFeedStatement(accountId, file),
  listBankTransactions: (
    accountId: number,
    params?: {
      match_status?: string;
      reconcile?: boolean;
      date_from?: string;
      date_to?: string;
      page?: number;
      page_size?: number;
    },
    options?: FreshRequestOptions
  ) => {
    const qs = new URLSearchParams();
    if (params?.reconcile) qs.set("reconcile", "true");
    else if (params?.match_status) qs.set("match_status", params.match_status);
    if (params?.date_from) qs.set("date_from", params.date_from);
    if (params?.date_to) qs.set("date_to", params.date_to);
    if (params?.page != null) qs.set("page", String(params.page));
    if (params?.page_size != null) qs.set("page_size", String(params.page_size));
    const q = qs.toString();
    const path = `/api/bank-feeds/accounts/${accountId}/transactions${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<BankTransactionList>(path);
  },
  listBankFeedImports: (
    accountId: number,
    params?: { page?: number; page_size?: number },
    options?: FreshRequestOptions
  ) => {
    const qs = new URLSearchParams();
    if (params?.page != null) qs.set("page", String(params.page));
    if (params?.page_size != null) qs.set("page_size", String(params.page_size));
    const q = qs.toString();
    const path = `/api/bank-feeds/accounts/${accountId}/imports${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<BankFeedImportList>(path);
  },
  getBankTransaction: (transactionId: number, options?: FreshRequestOptions) => {
    const path = `/api/bank-feeds/transactions/${transactionId}`;
    if (options?.fresh) bustGetCache(path);
    return request<BankTransaction>(path);
  },
  listBankTransactionAudit: (transactionId: number, options?: FreshRequestOptions) => {
    const path = `/api/bank-feeds/transactions/${transactionId}/audit`;
    if (options?.fresh) bustGetCache(path);
    return request<AuditLogEntry[]>(path);
  },
  listBankMatchTargets: (
    matchedType: "payment" | "collection",
    options?: FreshRequestOptions & { q?: string; limit?: number; bank_account_id?: number }
  ) => {
    const params = new URLSearchParams();
    params.set("matched_type", matchedType);
    if (options?.q?.trim()) params.set("q", options.q.trim());
    if (options?.limit != null) params.set("limit", String(options.limit));
    if (options?.bank_account_id != null) {
      params.set("bank_account_id", String(options.bank_account_id));
    }
    const path = `/api/bank-feeds/match-targets?${params.toString()}`;
    if (options?.fresh) bustGetCache(path);
    return request<BankMatchTarget[]>(path);
  },
  runBankFeedMatch: (accountId: number) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankMatchRunResult>(`/api/bank-feeds/accounts/${accountId}/match-run`, {
      method: "POST",
    });
  },
  runBankFeedCategorize: (accountId: number) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankCategorizeRunResult>(
      `/api/bank-feeds/accounts/${accountId}/categorize-run`,
      { method: "POST" }
    );
  },
  setBankTransactionCategory: (
    transactionId: number,
    body: {
      category_coa?: string | null;
      ledger?: string | null;
      sub_ledger?: string | null;
    }
  ) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransaction>(`/api/bank-feeds/transactions/${transactionId}/category`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  createBankTransactionMatch: (
    transactionId: number,
    body: {
      matched_type: "payment" | "collection";
      matched_id: number;
      allocated_amount?: number | null;
    }
  ) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransactionMatch>(
      `/api/bank-feeds/transactions/${transactionId}/matches`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
  },
  confirmBankMatch: (matchId: number) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransactionMatch>(`/api/bank-feeds/matches/${matchId}/confirm`, {
      method: "POST",
    });
  },
  unmatchBankMatch: (matchId: number, reason?: string | null) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransactionMatch>(`/api/bank-feeds/matches/${matchId}/unmatch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    });
  },
  excludeBankTransaction: (transactionId: number, reason?: string | null) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransaction>(
      `/api/bank-feeds/transactions/${transactionId}/exclude`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason ?? null }),
      }
    );
  },
  createBankJournal: (
    transactionId: number,
    body: {
      party_type: "vendor" | "customer";
      party_id?: number | null;
      create_party?: { name: string } | null;
      ledger: string;
      description: string;
      tax_rate_percent: number;
    }
  ) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransaction>(`/api/bank-feeds/transactions/${transactionId}/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  reverseBankCreate: (transactionId: number) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransaction>(
      `/api/bank-feeds/transactions/${transactionId}/reverse-create`,
      { method: "POST" }
    );
  },
  transferBankTransaction: (
    transactionId: number,
    body: { to_bank_account_id: number; description: string }
  ) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransaction>(
      `/api/bank-feeds/transactions/${transactionId}/transfer`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
  },
  listBankTransactionNotes: (transactionId: number, options?: FreshRequestOptions) => {
    const path = `/api/bank-feeds/transactions/${transactionId}/notes`;
    if (options?.fresh) bustGetCache(path);
    return request<BankTransactionNote[]>(path);
  },
  createBankTransactionNote: (transactionId: number, body: { body: string }) => {
    bustGetCacheByPrefix("/api/bank-feeds");
    return request<BankTransactionNote>(
      `/api/bank-feeds/transactions/${transactionId}/notes`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
  },
  listUnsettledSettlements: (
    params?: { page?: number; page_size?: number },
    options?: FreshRequestOptions
  ) => {
    const qs = new URLSearchParams();
    if (params?.page != null) qs.set("page", String(params.page));
    if (params?.page_size != null) qs.set("page_size", String(params.page_size));
    const q = qs.toString();
    const path = `/api/bank-feeds/unsettled-settlements${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<UnsettledSettlementList>(path);
  },
  getUnsettledSettlementsCount: (options?: FreshRequestOptions) => {
    const path = "/api/bank-feeds/unsettled-settlements/count";
    if (options?.fresh) bustGetCache(path);
    return request<UnsettledSettlementCount>(path);
  },
};

/** Inclusive invoice-date range for workbook export; omit both for all invoices. */
export type ReportDateFilter = {
  dateFrom?: string;
  dateTo?: string;
};

function reportDateQuery(filter?: ReportDateFilter): string {
  if (!filter?.dateFrom && !filter?.dateTo) return "";
  const p = new URLSearchParams();
  if (filter.dateFrom) p.set("date_from", filter.dateFrom);
  if (filter.dateTo) p.set("date_to", filter.dateTo);
  const q = p.toString();
  return q ? `?${q}` : "";
}

function defaultReportFilename(filter?: ReportDateFilter): string {
  const { dateFrom, dateTo } = filter ?? {};
  if (!dateFrom && !dateTo) return "output_workbook.xlsx";
  if (dateFrom && dateTo && dateFrom === dateTo) {
    return `output_workbook_${dateFrom}.xlsx`;
  }
  if (dateFrom && dateTo) {
    return `output_workbook_${dateFrom}_to_${dateTo}.xlsx`;
  }
  if (dateFrom) return `output_workbook_from_${dateFrom}.xlsx`;
  return `output_workbook_to_${dateTo}.xlsx`;
}

function defaultAuditLogFilename(filter?: ReportDateFilter): string {
  const { dateFrom, dateTo } = filter ?? {};
  if (!dateFrom && !dateTo) return "audit_log.csv";
  if (dateFrom && dateTo && dateFrom === dateTo) return `audit_log_${dateFrom}.csv`;
  if (dateFrom && dateTo) return `audit_log_${dateFrom}_to_${dateTo}.csv`;
  if (dateFrom) return `audit_log_from_${dateFrom}.csv`;
  return `audit_log_to_${dateTo}.csv`;
}

function defaultDocumentsBundleFilename(filter?: ReportDateFilter): string {
  const { dateFrom, dateTo } = filter ?? {};
  if (!dateFrom && !dateTo) return "documents_bundle.xlsx";
  if (dateFrom && dateTo && dateFrom === dateTo) {
    return `documents_bundle_${dateFrom}.xlsx`;
  }
  if (dateFrom && dateTo) return `documents_bundle_${dateFrom}_to_${dateTo}.xlsx`;
  if (dateFrom) return `documents_bundle_from_${dateFrom}.xlsx`;
  return `documents_bundle_to_${dateTo}.xlsx`;
}
