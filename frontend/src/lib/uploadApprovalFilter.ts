export type UploadApprovalStatusKey = "review" | "processing" | "approved" | "rejected";
export type UploadApprovalFilterKey = "all" | UploadApprovalStatusKey;

export type UploadApprovalBoardCounts = Record<UploadApprovalFilterKey, number>;

export const UPLOAD_APPROVAL_STATUS_KEYS: readonly UploadApprovalStatusKey[] = [
  "review",
  "processing",
  "approved",
  "rejected",
] as const;

export const UPLOAD_APPROVAL_STATUS_FILTERS: {
  key: UploadApprovalStatusKey;
  label: string;
}[] = [
  { key: "review", label: "To Review" },
  { key: "processing", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

/** @deprecated Use UPLOAD_APPROVAL_STATUS_FILTERS — "All" is no longer shown. */
export const UPLOAD_APPROVAL_FILTERS: {
  key: UploadApprovalFilterKey;
  label: string;
}[] = [
  { key: "all", label: "All" },
  ...UPLOAD_APPROVAL_STATUS_FILTERS,
];

const STATUS_LABEL: Record<UploadApprovalStatusKey, string> = {
  review: "To Review",
  processing: "Processing",
  approved: "Approved",
  rejected: "Rejected",
};

export const EMPTY_UPLOAD_APPROVAL_COUNTS: UploadApprovalBoardCounts = {
  all: 0,
  review: 0,
  processing: 0,
  approved: 0,
  rejected: 0,
};

/** Stable empty filter — never allocate a new `[]` for "All". */
export const EMPTY_UPLOAD_APPROVAL_FILTER: UploadApprovalStatusKey[] = [];

export function approvalBoardCountsEqual(
  a: UploadApprovalBoardCounts | null | undefined,
  b: UploadApprovalBoardCounts | null | undefined
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.all === b.all &&
    a.review === b.review &&
    a.processing === b.processing &&
    a.approved === b.approved &&
    a.rejected === b.rejected
  );
}

function isStatusKey(value: string): value is UploadApprovalStatusKey {
  return (UPLOAD_APPROVAL_STATUS_KEYS as readonly string[]).includes(value);
}

/** Empty array means All (no column filter). */
export function parseUploadApprovalFilter(value: string | null): UploadApprovalStatusKey[] {
  if (!value || value === "all") return EMPTY_UPLOAD_APPROVAL_FILTER;
  const selected = new Set<UploadApprovalStatusKey>();
  for (const part of value.split(",")) {
    const token = part.trim().toLowerCase();
    if (isStatusKey(token)) selected.add(token);
  }
  if (selected.size === 0) return EMPTY_UPLOAD_APPROVAL_FILTER;
  return UPLOAD_APPROVAL_STATUS_KEYS.filter((key) => selected.has(key));
}

export function serializeUploadApprovalFilter(keys: UploadApprovalStatusKey[]): string | null {
  if (keys.length === 0 || keys.length === UPLOAD_APPROVAL_STATUS_KEYS.length) return null;
  return keys.join(",");
}

export function uploadApprovalFilterLabel(keys: UploadApprovalStatusKey[]): string {
  if (keys.length === 0) return "Filter";
  return keys.map((key) => STATUS_LABEL[key]).join(", ");
}

export function toggleUploadApprovalFilter(
  current: UploadApprovalStatusKey[],
  key: UploadApprovalFilterKey
): UploadApprovalStatusKey[] {
  if (key === "all") return EMPTY_UPLOAD_APPROVAL_FILTER;
  if (current.includes(key)) return current.filter((item) => item !== key);
  return UPLOAD_APPROVAL_STATUS_KEYS.filter((item) => item === key || current.includes(item));
}

export function boardCountsFromMeta(meta: {
  approval_review_count?: number | null;
  approval_processing_count?: number | null;
  approval_approved_count?: number | null;
  approval_rejected_count?: number | null;
} | null | undefined): UploadApprovalBoardCounts {
  const review = meta?.approval_review_count ?? 0;
  const processing = meta?.approval_processing_count ?? 0;
  const approved = meta?.approval_approved_count ?? 0;
  const rejected = meta?.approval_rejected_count ?? 0;
  return {
    all: review + processing + approved + rejected,
    review,
    processing,
    approved,
    rejected,
  };
}

export type UploadDocumentAreaKey = "team" | "expenses" | "purchase" | "sales";

export const UPLOAD_DOCUMENT_AREA_FILTERS: {
  key: UploadDocumentAreaKey;
  label: string;
  routeTarget: string;
  moduleKey: string;
  path: string;
}[] = [
  { key: "team", label: "Team Exp", routeTarget: "Team Expenses", moduleKey: "team_expenses", path: "/team-expenses" },
  { key: "expenses", label: "Expenses Mgt", routeTarget: "Expenses Management", moduleKey: "expenses", path: "/expenses" },
  { key: "purchase", label: "Purchase Mgt", routeTarget: "Purchase Management", moduleKey: "purchase", path: "/purchases" },
  { key: "sales", label: "Sales Mgt", routeTarget: "Sales Management", moduleKey: "sales", path: "/sales" },
];

const UPLOAD_DOCUMENT_AREA_KEYS: readonly UploadDocumentAreaKey[] = UPLOAD_DOCUMENT_AREA_FILTERS.map(
  (item) => item.key
);

const AREA_BY_KEY = Object.fromEntries(
  UPLOAD_DOCUMENT_AREA_FILTERS.map((item) => [item.key, item])
) as Record<UploadDocumentAreaKey, (typeof UPLOAD_DOCUMENT_AREA_FILTERS)[number]>;

const OPERATIONS_VIEW_TO_AREA: Record<string, UploadDocumentAreaKey> = {
  "team-expenses": "team",
  expenses: "expenses",
  purchases: "purchase",
  sales: "sales",
};

function isAreaKey(value: string): value is UploadDocumentAreaKey {
  return value in AREA_BY_KEY;
}

/** Empty array means All (no area filter). Comma-separated `area` is supported. */
export function parseUploadDocumentAreas(
  area: string | null,
  view?: string | null
): UploadDocumentAreaKey[] {
  if (area) {
    const selected = new Set<UploadDocumentAreaKey>();
    for (const part of area.split(",")) {
      const token = part.trim().toLowerCase();
      if (isAreaKey(token)) selected.add(token);
    }
    return UPLOAD_DOCUMENT_AREA_KEYS.filter((key) => selected.has(key));
  }
  if (view && view in OPERATIONS_VIEW_TO_AREA) return [OPERATIONS_VIEW_TO_AREA[view]!];
  return [];
}

export function parseUploadDocumentArea(
  area: string | null,
  view?: string | null
): UploadDocumentAreaKey | null {
  return parseUploadDocumentAreas(area, view)[0] ?? null;
}

export function serializeUploadDocumentAreas(keys: UploadDocumentAreaKey[]): string | null {
  if (keys.length === 0) return null;
  return keys.join(",");
}

export function serializeUploadDocumentArea(key: UploadDocumentAreaKey | null): string | null {
  return key;
}

export function toggleUploadDocumentArea(
  current: UploadDocumentAreaKey[],
  key: UploadDocumentAreaKey
): UploadDocumentAreaKey[] {
  if (current.includes(key)) return current.filter((item) => item !== key);
  return UPLOAD_DOCUMENT_AREA_KEYS.filter((item) => item === key || current.includes(item));
}

/** Exclusive area chip: Summary is `[]`, each other chip is a single key. */
export function selectUploadDocumentArea(
  current: UploadDocumentAreaKey[],
  key: UploadDocumentAreaKey
): UploadDocumentAreaKey[] {
  if (current.length === 1 && current[0] === key) return [];
  return [key];
}

export function routeTargetsForDocumentAreas(keys: UploadDocumentAreaKey[]): string | undefined {
  if (keys.length === 0) return undefined;
  return keys.map((key) => AREA_BY_KEY[key].routeTarget).join(",");
}

export function routeTargetForDocumentArea(key: UploadDocumentAreaKey | null): string | undefined {
  return routeTargetsForDocumentAreas(key ? [key] : []);
}
