export type UploadApprovalStatusKey = "review" | "processing" | "approved" | "rejected";
export type UploadApprovalFilterKey = "all" | UploadApprovalStatusKey;

export type UploadApprovalBoardCounts = Record<UploadApprovalFilterKey, number>;

export const UPLOAD_APPROVAL_STATUS_KEYS: readonly UploadApprovalStatusKey[] = [
  "review",
  "processing",
  "approved",
  "rejected",
] as const;

export const UPLOAD_APPROVAL_FILTERS: {
  key: UploadApprovalFilterKey;
  label: string;
}[] = [
  { key: "all", label: "All" },
  { key: "review", label: "To review" },
  { key: "processing", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

const STATUS_LABEL: Record<UploadApprovalStatusKey, string> = {
  review: "To review",
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
