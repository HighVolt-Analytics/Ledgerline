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

export type PolicyRule = { id: string; condition: string; approver: string };

export type LocalApprovalPolicy = {
  locked: boolean;
  rules: PolicyRule[];
  matrix: Record<ApprovalRole, Record<ApprovalAction, boolean>>;
};

export const DEFAULT_APPROVAL_RULES: PolicyRule[] = [
  { id: "ap1", condition: "Invoices > 5,000", approver: "CFO approval" },
  { id: "ap2", condition: "Marketing Expense invoices", approver: "Marketing Lead" },
  { id: "ap3", condition: "Suspense-routed invoices", approver: "Finance Controller" },
  { id: "ap4", condition: "New vendor (first invoice)", approver: "Bookkeeper review" },
];

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
