import type {
  ApprovalPolicy,
  BillingState,
  AuditLogEntry,
  ActivityItem,
  ApiEnvelope,
  AppSettings,
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
  PaymentApi,
  PurchaseOrderApi,
  PurchaseDossier,
  DashboardOverview,
  DashboardStats,
  ReportsAnalytics,
  ReportDocumentRow,
  Invoice,
  InvoiceDetails,
  LedgerLinkResponse,
  InvoiceUpdatePayload,
  Tenant,
  PlatformTenantSummary,
  PlatformTenantDetail,
  PlatformTenantModule,
  MatrixRow,
  PipelineAuditStep,
  InvoiceClassificationAudit,
  ProcessingStatus,
  RuleBookConfig,
  RuleBookChangelogEntry,
  RuleBookRulesPayload,
  RuleBookEvaluateRequest,
  RuleBookEvaluateResult,
  ReconciliationOverview,
  TokenResponse,
  TenantMembersList,
  TenantMember,
  TenantInviteCreated,
  InvitePreview,
  InviteAcceptResult,
  InstitutionSettings,
  OnboardingStatus,
  UserPermissions,
  Vendor,
  VaultTreeResponse,
  VaultMigrateResponse,
  WalletSummary,
  WhatsappStatus,
} from "./types";

import { LEDGERLINK_BASENAME } from "@/lib/routerBasename";
import { tenantIdFromToken } from "@/lib/authToken";

/** Public URL prefix; endpoint paths include /api (e.g. BASE + /api/auth/login). */
const BASE =
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.PROD ? LEDGERLINK_BASENAME : "");

/** Dedupe concurrent GETs and cache briefly to avoid StrictMode double-fetch. */
const GET_CACHE_MS = 30_000;
const inflightGets = new Map<string, Promise<unknown>>();
const getCache = new Map<string, { data: unknown; at: number }>();

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

export function setAuthToken(token: string | null) {
  authToken = token;
  clearGetCache();
}

export function setAuthUser(user: AuthUser | null) {
  authUser = user;
}

function getScopedAuthHeaders(init?: RequestInit): Headers {
  const headers = withAuthHeaders(init);
  // JWT is the source of truth — cached authUser can lag after tenant UUID migration.
  const tid = tenantIdFromToken(authToken) ?? authUser?.tenant_id;
  if (tid) {
    headers.set("X-Tenant-Id", String(tid));
  }
  return headers;
}

export function clearGetCache() {
  getCache.clear();
  inflightGets.clear();
}

function getRequestKey(path: string, method: string) {
  const tid = tenantIdFromToken(authToken) ?? authUser?.tenant_id ?? "anon";
  return `${tid}:${method}:${path}`;
}

function invalidateGetCache() {
  getCache.clear();
}

function bustGetCache(path: string, method = "GET") {
  const key = getRequestKey(path, method);
  getCache.delete(key);
  inflightGets.delete(key);
  const metaKey = getRequestKey(`${path}#meta`, method);
  getCache.delete(metaKey);
  inflightGets.delete(metaKey);
}

export type FreshRequestOptions = { fresh?: boolean };

export type ApiRequestOptions = RequestInit & { timeoutMs?: number };

function withAuthHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }
  return headers;
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
): Promise<{ blob: Blob; filename: string }> {
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
  };
}

async function fetchEnvelope<T>(path: string, init?: ApiRequestOptions): Promise<T> {
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
      if (
        res.status === 401 &&
        authToken &&
        path !== "/api/auth/me" &&
        path !== "/api/auth/refresh"
      ) {
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
  if (method !== "GET") {
    invalidateGetCache();               /** Invalidate cache for non-GET requests */
    return fetchEnvelope<T>(path, init);   /** Fetch data from backend */
  }

  const key = getRequestKey(path, method);
  const cached = getCache.get(key);
  if (cached && Date.now() - cached.at < GET_CACHE_MS) {
    return cached.data as T;
  }

  const inflight = inflightGets.get(key);
  if (inflight) return inflight as Promise<T>;

  const promise = fetchEnvelope<T>(path, init)
    .then((data) => {
      getCache.set(key, { data, at: Date.now() });
      return data;
    })
    .finally(() => {
      inflightGets.delete(key);
    });

  inflightGets.set(key, promise);
  return promise;
}

async function requestWithMeta<T>(
  path: string,
  init?: RequestInit
): Promise<{ data: T; meta: ApiEnvelope<T>["meta"] }> {
  const method = (init?.method ?? "GET").toUpperCase();
  const key = getRequestKey(`${path}#meta`, method);

  if (method === "GET") {
    const cached = getCache.get(key);
    if (cached && Date.now() - cached.at < GET_CACHE_MS) {
      return cached.data as { data: T; meta: ApiEnvelope<T>["meta"] };
    }
    const inflight = inflightGets.get(key);
    if (inflight) {
      return inflight as Promise<{ data: T; meta: ApiEnvelope<T>["meta"] }>;
    }
  } else {
    invalidateGetCache();
  }

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
    return { data: json.data, meta: json.meta };
  })();

  if (method === "GET") {
    inflightGets.set(
      key,
      promise.then((payload) => {
        getCache.set(key, { data: payload, at: Date.now() });
        return payload;
      })
    );
    return promise.finally(() => inflightGets.delete(key));
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
    country?: string;
    timezone?: string;
    locale?: string;
  }) =>
    request<InstitutionSettings>("/api/tenants/current/institution", {
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
  enterClientWorkspace: (tenantId: string) =>
    request<TokenResponse>(`/api/platform/tenants/${tenantId}/enter-workspace`, {
      method: "POST",
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

  getNavBadges: () => request<NavBadges>("/api/dashboard/badges"),
  getStats: () => request<DashboardStats>("/api/dashboard/stats"),
  getDashboardOverview: (activityLimit = 10, month?: string) => {
    const params = new URLSearchParams({
      activity_limit: String(activityLimit),
    });
    if (month) params.set("month", month);
    return request<DashboardOverview>(`/api/dashboard/overview?${params}`);
  },
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
  getInvoice: (id: number) => request<InvoiceDetails>(`/api/invoices/${id}`),
  updateInvoice: (id: number, body: InvoiceUpdatePayload) =>
    request<InvoiceDetails>(`/api/invoices/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getInvoicePipeline: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/pipeline`;
    if (options?.fresh) bustGetCache(path);
    return request<{ steps: PipelineAuditStep[] }>(path).then((r) => r.steps);
  },
  getInvoiceClassificationAudit: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/classification-audit`;
    if (options?.fresh) bustGetCache(path);
    return request<InvoiceClassificationAudit>(path);
  },
  getPurchaseDossier: (id: number, options?: FreshRequestOptions) => {
    const path = `/api/invoices/${id}/purchase-dossier`;
    if (options?.fresh) bustGetCache(path);
    return request<PurchaseDossier>(path);
  },
  getMatrixWithMeta: (params?: Record<string, string>, options?: FreshRequestOptions) => {
    const q = new URLSearchParams(params).toString();
    const path = `/api/matrix${q ? `?${q}` : ""}`;
    if (options?.fresh) bustGetCache(path);
    return requestWithMeta<MatrixRow[]>(path);
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
  reprocess: (id: number) =>
    request<Invoice>(`/api/invoices/${id}/reprocess`, { method: "POST" }),
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
  approve: (id: number) =>
    request<Invoice>(`/api/approvals/${id}/approve`, { method: "POST" }),
  reject: (id: number) =>
    request<Invoice>(`/api/approvals/${id}/reject`, { method: "POST" }),
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
    bustGetCache("/api/approvals");
    bustGetCache("/api/invoices");
    return request<void>(`/api/approvals/${id}`, { method: "DELETE" });
  },
  listVendors: (options?: FreshRequestOptions) => {
    const path = "/api/vendors";
    if (options?.fresh) bustGetCache(path);
    return request<Vendor[]>(path);
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
  listVendorMasters: (options?: FreshRequestOptions) => {
    const path = "/api/vendor-masters";
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
  listEmployeeMasters: (options?: FreshRequestOptions) => {
    const path = "/api/employee-masters";
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
  getRuleBookConfig: () => request<RuleBookConfig>("/api/rule-book/config"),
  evaluateRuleBook: (body: RuleBookEvaluateRequest = {}) =>
    request<RuleBookEvaluateResult>("/api/rule-book/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getVaultTree: (options?: FreshRequestOptions) => {
    const path = "/api/vault/tree";
    if (options?.fresh) bustGetCache(path);
    return request<VaultTreeResponse>(path);
  },
  migrateVault: () =>
    request<VaultMigrateResponse>("/api/vault/migrate", { method: "POST" }),
  putRuleBookConfig: (body: RuleBookRulesPayload) =>
    request<RuleBookConfig>("/api/rule-book/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteRuleBookDocumentType: (code: string) =>
    request<RuleBookConfig>(
      `/api/rule-book/document-types/${encodeURIComponent(code.trim())}`,
      { method: "DELETE" }
    ),
  analyzeDocumentTypeSamples: (
    formData: FormData,
    options?: { timeoutMs?: number }
  ) =>
    request<import("@/lib/documentTypeSampleAnalysis").DocumentTypeSampleProposal>(
      "/api/rule-book/document-types/analyze-samples",
      { method: "POST", body: formData, timeoutMs: options?.timeoutMs }
    ),
  getRuleBookChangelog: (limit = 20) =>
    request<RuleBookChangelogEntry[]>(`/api/rule-book/changelog?limit=${limit}`),
  getSettings: () => request<AppSettings>("/api/settings"),
  listReconciliation: () => request<DailyReconciliation[]>("/api/reconciliation/daily"),
  getReconciliationOverview: () =>
    request<ReconciliationOverview>("/api/reconciliation/overview"),
  getLedgerLink: (options?: FreshRequestOptions) => {
    const path = "/api/ledger-link";
    if (options?.fresh) bustGetCache(path);
    return request<LedgerLinkResponse>(path);
  },
  getBilling: () => request<BillingState>("/api/billing"),
  patchBilling: (body: { auto_recharge?: boolean; threshold?: number }) =>
    request<BillingState>("/api/billing", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  purchaseBillingPack: (packId: string) =>
    request<BillingState>("/api/billing/purchase", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pack_id: packId }),
    }),
  getReportsAnalytics: (month: string) =>
    request<ReportsAnalytics>(`/api/reports/analytics?month=${encodeURIComponent(month)}`),
  getReportDocuments: (filter?: ReportDateFilter) =>
    request<ReportDocumentRow[]>(`/api/reports/documents${reportDateQuery(filter)}`),
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
  downloadAuditLogCsv: async (month: string) => {
    const params = new URLSearchParams({
      month,
      document_only: "true",
      dedupe: "true",
    });
    const { blob, filename } = await requestBlob(
      `/api/audit-log/export?${params.toString()}`,
      undefined,
      `audit_log_${month}.csv`
    );
    saveBlobAsFile(blob, filename);
  },
  listPurchases: (options?: FreshRequestOptions) => {
    const path = "/api/purchases";
    if (options?.fresh) bustGetCache(path);
    return request<PurchaseOrderApi[]>(path);
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
  getWalletSummary: (options?: FreshRequestOptions) => {
    const path = "/api/payments/wallet-summary";
    if (options?.fresh) bustGetCache(path);
    return request<WalletSummary>(path);
  },
  listPayments: (status?: string, options?: FreshRequestOptions) => {
    const path = status ? `/api/payments?status=${encodeURIComponent(status)}` : "/api/payments";
    if (options?.fresh) bustGetCache(path);
    return request<PaymentApi[]>(path);
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
