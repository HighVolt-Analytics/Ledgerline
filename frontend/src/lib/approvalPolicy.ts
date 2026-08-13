export const APPROVAL_ROLES = [
  "Admin",
  "Functional manager",
  "Functional supervisor",
  "Finance head",
  "Bookkeeper",
  "Auditor",
  "User",
] as const;
export const APPROVAL_ACTIONS = [
  "View",
  "Comment",
  "Approve",
  "Reject",
  "Post",
  "Edit Policy",
  "Manage Users",
] as const;

export type ApprovalRole = (typeof APPROVAL_ROLES)[number];
export type ApprovalAction = (typeof APPROVAL_ACTIONS)[number];

export type ApprovalQuorumMode = "one_way" | "two_way" | "three_way";

export const APPROVAL_MODULE_ROLES = [
  "Admin",
  "Functional manager",
  "Functional supervisor",
  "Finance head",
] as const;

export type ApprovalModuleRole = (typeof APPROVAL_MODULE_ROLES)[number];

export const APPROVAL_MATRIX_MODULES = [
  "team_expenses",
  "expenses",
  "purchase",
  "sales",
] as const;

export type ApprovalMatrixModule = (typeof APPROVAL_MATRIX_MODULES)[number];

export const APPROVAL_MATRIX_MODULE_LABELS: Record<ApprovalMatrixModule, string> = {
  team_expenses: "Team Expenses",
  expenses: "Expenses Management",
  purchase: "Purchase Management",
  sales: "Sales Management",
};

export const APPROVAL_QUORUM_MODE_OPTIONS: {
  value: ApprovalQuorumMode;
  label: string;
}[] = [
  { value: "one_way", label: "1-way (any 1 of 4)" },
  { value: "two_way", label: "2-way (any 2 of 4)" },
  { value: "three_way", label: "3-way (any 3 of 4)" },
];

export type PolicyRule = { id: string; condition: string; approver: string };

export type ApprovalMatrixConfig = {
  by_module: Record<ApprovalMatrixModule, ApprovalQuorumMode>;
  approver_roles_by_module: Record<
    ApprovalMatrixModule,
    Record<ApprovalModuleRole, boolean>
  >;
};

export type LocalApprovalPolicy = {
  locked: boolean;
  rules: PolicyRule[];
  matrix: Record<ApprovalRole, Record<ApprovalAction, boolean>>;
  approval_matrix: ApprovalMatrixConfig;
};

export const DEFAULT_APPROVAL_RULES: PolicyRule[] = [
  { id: "ap1", condition: "Invoices > 5,000", approver: "CFO approval" },
  { id: "ap2", condition: "Marketing Expense invoices", approver: "Marketing Lead" },
  { id: "ap3", condition: "Suspense-routed invoices", approver: "Finance Controller" },
  { id: "ap4", condition: "New vendor (first invoice)", approver: "Bookkeeper review" },
];

export const DEFAULT_APPROVAL_MATRIX_BY_MODULE: Record<
  ApprovalMatrixModule,
  ApprovalQuorumMode
> = {
  team_expenses: "one_way",
  expenses: "one_way",
  purchase: "two_way",
  sales: "one_way",
};

export const DEFAULT_APPROVER_ROLES_BY_MODULE: Record<
  ApprovalMatrixModule,
  Record<ApprovalModuleRole, boolean>
> = {
  team_expenses: {
    Admin: true,
    "Functional manager": false,
    "Functional supervisor": false,
    "Finance head": false,
  },
  expenses: {
    Admin: true,
    "Functional manager": false,
    "Functional supervisor": false,
    "Finance head": false,
  },
  purchase: {
    Admin: true,
    "Functional manager": true,
    "Functional supervisor": false,
    "Finance head": false,
  },
  sales: {
    Admin: true,
    "Functional manager": false,
    "Functional supervisor": false,
    "Finance head": false,
  },
};

const LEADERSHIP: Record<ApprovalAction, boolean> = {
  View: true,
  Comment: true,
  Approve: true,
  Reject: true,
  Post: true,
  "Edit Policy": false,
  "Manage Users": false,
};

const SUPERVISOR: Record<ApprovalAction, boolean> = {
  View: true,
  Comment: true,
  Approve: true,
  Reject: true,
  Post: false,
  "Edit Policy": false,
  "Manage Users": false,
};

const READ_COMMENT: Record<ApprovalAction, boolean> = {
  View: true,
  Comment: true,
  Approve: false,
  Reject: false,
  Post: false,
  "Edit Policy": false,
  "Manage Users": false,
};

const VIEW_ONLY: Record<ApprovalAction, boolean> = {
  View: true,
  Comment: false,
  Approve: false,
  Reject: false,
  Post: false,
  "Edit Policy": false,
  "Manage Users": false,
};

export const DEFAULT_APPROVAL_MATRIX: Record<
  ApprovalRole,
  Record<ApprovalAction, boolean>
> = {
  Admin: Object.fromEntries(APPROVAL_ACTIONS.map((a) => [a, true])) as Record<
    ApprovalAction,
    boolean
  >,
  "Functional manager": { ...LEADERSHIP },
  "Functional supervisor": { ...SUPERVISOR },
  "Finance head": { ...LEADERSHIP },
  Bookkeeper: { ...READ_COMMENT },
  Auditor: { ...READ_COMMENT },
  User: { ...VIEW_ONLY },
};

export function normalizeApprovalMatrixConfig(
  raw: Partial<ApprovalMatrixConfig> | null | undefined
): ApprovalMatrixConfig {
  const by_module = { ...DEFAULT_APPROVAL_MATRIX_BY_MODULE };
  const approver_roles_by_module = Object.fromEntries(
    APPROVAL_MATRIX_MODULES.map((module) => [
      module,
      { ...DEFAULT_APPROVER_ROLES_BY_MODULE[module] },
    ])
  ) as Record<ApprovalMatrixModule, Record<ApprovalModuleRole, boolean>>;
  const source: Partial<Record<ApprovalMatrixModule, ApprovalQuorumMode>> =
    raw?.by_module ?? {};
  for (const key of APPROVAL_MATRIX_MODULES) {
    const val = source[key];
    if (val === "one_way" || val === "two_way" || val === "three_way") {
      by_module[key] = val;
    }

    const moduleRoles = raw?.approver_roles_by_module?.[key];
    if (moduleRoles) {
      for (const role of APPROVAL_MODULE_ROLES) {
        if (typeof moduleRoles[role] === "boolean") {
          approver_roles_by_module[key][role] = moduleRoles[role];
        }
      }
    }

    const enabledCount = APPROVAL_MODULE_ROLES.reduce(
      (acc, role) => acc + (approver_roles_by_module[key][role] ? 1 : 0),
      0
    );
    if (enabledCount <= 0) {
      approver_roles_by_module[key].Admin = true;
      by_module[key] = "one_way";
    } else if (enabledCount === 1) {
      by_module[key] = "one_way";
    } else if (enabledCount === 2) {
      by_module[key] = "two_way";
    } else {
      by_module[key] = "three_way";
    }
  }
  return { by_module, approver_roles_by_module };
}
