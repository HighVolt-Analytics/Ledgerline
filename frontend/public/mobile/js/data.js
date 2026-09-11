/* Quantum Ledger Link — mobile dataset.
   Identity (me / tenant / entities) is filled from the LedgerLink session at boot.
   Approvals and My items are loaded from LedgerLink APIs. */

const QLL = {
  tenant: '',
  entities: [],

  me: {
    name: '',
    initials: '',
    email: '',
    role: '',
    dept: '',
    quarter: '',
    remaining: 0,
    approved: 0,
    leftPct: null,
    hasBudget: false,
    budgetLineKey: 'all',
    budgetAll: null,
    budgetLines: [],
    budgetTree: [],
    coaParentChildren: {},
    advance: null,
    delegate: { on: false, to: '' }
  },

  capture: {},

  /* Approvals: GET /api/approvals (state.approvals in app.js) */
  approvals: [],

  /* My items: GET /api/invoices?mine=true */
  myItems: {
    claims: [],
    invoices: [],
    advances: [],
    all: []
  },

  /* Files vault — loaded later; keep empty (no demo rows). */
  files: [],
  fileFilters: ['Mine', 'Invoices', 'Receipts', 'Contracts', 'Claims', 'This month']
};
