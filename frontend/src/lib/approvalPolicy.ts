/** Canonical privilege-matrix helpers for Policy & privileges. */

export const APPROVAL_ROLES = [
  "Employee",
  "Manager",
  "Department Head",
  "Finance Manager",
  "CFO",
  "Director",
  "Admin",
] as const;

export const APPROVAL_ACTIONS = [
  "View",
  "Comment",
  "Approve",
  "Edit Policy",
  "Manage Users",
] as const;

export type ApprovalRole = (typeof APPROVAL_ROLES)[number];
export type ApprovalAction = (typeof APPROVAL_ACTIONS)[number];

/** Roles assignable in the amount approval matrix (not Employee). */
export const APPROVAL_MATRIX_ASSIGNABLE_ROLES = [
  "Manager",
  "Department Head",
  "Finance Manager",
  "CFO",
  "Director",
  "Admin",
] as const;

export type ApprovalMatrixAssignableRole = (typeof APPROVAL_MATRIX_ASSIGNABLE_ROLES)[number];

/** Legacy privilege columns folded into Approve. */
export const APPROVE_ACTION_ALIASES = ["Approve", "Reject", "Post", "Publish"] as const;

/** Map legacy privilege role labels onto the current set. */
export const LEGACY_APPROVAL_ROLE_LABELS: Record<string, ApprovalRole> = {
  Approver: "Manager",
  Viewer: "Employee",
  User: "Employee",
  "Functional manager": "Manager",
  "Functional supervisor": "Department Head",
  "Finance head": "Finance Manager",
  Bookkeeper: "CFO",
  Auditor: "Director",
};

/** Per-role approval amount ceiling. null = unlimited. Enforced on approve/payment. */
export type ApprovalLimitsByRole = Record<ApprovalRole, number | null>;

export type AmountApprovalTierRow = {
  id: string;
  min_amount: number;
  max_amount: number | null;
  approval_1: ApprovalMatrixAssignableRole | null;
  approval_2: ApprovalMatrixAssignableRole | null;
  /** Payment approval */
  approval_3: ApprovalMatrixAssignableRole | null;
};

export type LocalApprovalPolicy = {
  locked: boolean;
  matrix: Record<ApprovalRole, Record<ApprovalAction, boolean>>;
  /** Max amount this role may personally approve; null = unlimited. */
  approval_limits: ApprovalLimitsByRole;
  amount_approval_tiers: AmountApprovalTierRow[];
};

const LEADERSHIP: Record<ApprovalAction, boolean> = {
  View: true,
  Comment: true,
  Approve: true,
  "Edit Policy": false,
  "Manage Users": false,
};

const VIEW_ONLY: Record<ApprovalAction, boolean> = {
  View: true,
  Comment: false,
  Approve: false,
  "Edit Policy": false,
  "Manage Users": false,
};

export const DEFAULT_APPROVAL_MATRIX: Record<
  ApprovalRole,
  Record<ApprovalAction, boolean>
> = {
  Employee: { ...VIEW_ONLY },
  Manager: { ...LEADERSHIP },
  "Department Head": { ...LEADERSHIP },
  "Finance Manager": { ...LEADERSHIP },
  CFO: { ...LEADERSHIP },
  Director: { ...LEADERSHIP },
  Admin: Object.fromEntries(APPROVAL_ACTIONS.map((a) => [a, true])) as Record<
    ApprovalAction,
    boolean
  >,
};

export const DEFAULT_APPROVAL_LIMITS: ApprovalLimitsByRole = Object.fromEntries(
  APPROVAL_ROLES.map((role) => [role, null])
) as ApprovalLimitsByRole;

export const DEFAULT_AMOUNT_APPROVAL_TIERS: AmountApprovalTierRow[] = [
  {
    id: "tier-0-5k",
    min_amount: 0,
    max_amount: 5000,
    approval_1: "Manager",
    approval_2: null,
    approval_3: null,
  },
  {
    id: "tier-5k-20k",
    min_amount: 5001,
    max_amount: 20000,
    approval_1: "Manager",
    approval_2: "Department Head",
    approval_3: null,
  },
  {
    id: "tier-20k-50k",
    min_amount: 20001,
    max_amount: 50000,
    approval_1: "Department Head",
    approval_2: "Finance Manager",
    approval_3: null,
  },
  {
    id: "tier-50k-250k",
    min_amount: 50001,
    max_amount: 250000,
    approval_1: "Department Head",
    approval_2: "Finance Manager",
    approval_3: "CFO",
  },
  {
    id: "tier-250k-plus",
    min_amount: 250001,
    max_amount: null,
    approval_1: "Finance Manager",
    approval_2: "CFO",
    approval_3: "Director",
  },
];

function normalizeMatrixRole(raw: unknown): ApprovalMatrixAssignableRole | null {
  if (raw == null || raw === "" || raw === "—") return null;
  const text = String(raw).trim();
  const mapped = LEGACY_APPROVAL_ROLE_LABELS[text] ?? text;
  return (APPROVAL_MATRIX_ASSIGNABLE_ROLES as readonly string[]).includes(mapped)
    ? (mapped as ApprovalMatrixAssignableRole)
    : null;
}

export function normalizeApprovalLimits(
  raw: Partial<Record<string, number | null | string>> | null | undefined,
  roleRemap: Record<string, ApprovalRole> = LEGACY_APPROVAL_ROLE_LABELS
): ApprovalLimitsByRole {
  const out: ApprovalLimitsByRole = { ...DEFAULT_APPROVAL_LIMITS };
  if (!raw || typeof raw !== "object") return out;
  for (const [key, value] of Object.entries(raw)) {
    const role =
      roleRemap[key] ??
      (APPROVAL_ROLES.includes(key as ApprovalRole) ? (key as ApprovalRole) : null);
    if (!role) continue;
    if (value === null || value === undefined || value === "") {
      out[role] = null;
      continue;
    }
    const num = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
    out[role] = Number.isFinite(num) && num >= 0 ? num : null;
  }
  return out;
}

export function normalizeAmountApprovalTiers(raw: unknown): AmountApprovalTierRow[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return DEFAULT_AMOUNT_APPROVAL_TIERS.map((t) => ({ ...t }));
  }
  const out: AmountApprovalTierRow[] = [];
  for (let i = 0; i < raw.length; i++) {
    const row = raw[i];
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const min = Number(r.min_amount);
    const maxRaw = r.max_amount;
    const max =
      maxRaw === null || maxRaw === undefined || maxRaw === "" ? null : Number(maxRaw);
    out.push({
      id: String(r.id || `tier-${i}`),
      min_amount: Number.isFinite(min) && min >= 0 ? min : 0,
      max_amount: max != null && Number.isFinite(max) && max >= 0 ? max : null,
      approval_1: normalizeMatrixRole(r.approval_1),
      approval_2: normalizeMatrixRole(r.approval_2),
      approval_3: normalizeMatrixRole(r.approval_3),
    });
  }
  return out.length ? out : DEFAULT_AMOUNT_APPROVAL_TIERS.map((t) => ({ ...t }));
}

export function formatAmountTierLabel(row: AmountApprovalTierRow): string {
  const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (row.max_amount == null) return `>${fmt(Math.max(0, row.min_amount - 1))}`;
  if (row.min_amount <= 0) return `$0–$${fmt(row.max_amount)}`;
  return `$${fmt(row.min_amount)}–$${fmt(row.max_amount)}`;
}
