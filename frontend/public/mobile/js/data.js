/* Quantum Ledger Link — mobile dataset.
   Identity (me / tenant / entities) is filled from the LedgerLink session at boot.
   Remaining list/sample rows are UI placeholders until those screens are API-wired. */

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
    budget: 0,
    claimed: 0,
    approved: 0,
    advance: null,
    delegate: { on: false, to: '' }
  },

  /* Home recent activity: mine=true invoices for the signed-in employee (see LLCapture.refreshHomeActivity). */
  activity: [],

  /* Capture review uses live invoice extraction — this stub is unused. */
  capture: {},

  /* --- Approvals inbox: loaded live from GET /api/approvals when privilege matrix grants Approve/Reject --- */
  approvals: [],

  rejectReasons: ['Missing receipt', 'Over budget', 'Wrong cost centre', 'Duplicate', 'Needs PO', 'Policy breach'],
  advanceAmounts: [500, 1000, 2500, 5000],
  advancePurposes: ['Client travel', 'Site visit', 'Trade event', 'Freight deposit'],

  /* --- My items: loaded live from GET /api/invoices?mine=true (Team Expenses claims/advances) --- */
  myItems: {
    claims: [],
    invoices: [],
    advances: []
  },

  /* --- Files vault --- */
  files: [
    { n: 'Pacific Freight Holdings — Tax invoice', dt: 'DT-01', type: 'Invoice', vendor: 'Pacific Freight Holdings', date: '4 Sep 2026', mine: true, size: '212 KB', ret: '7 yr', enc: 'AES-256' },
    { n: 'Aurora Cloud Services — Renewal invoice', dt: 'DT-15', type: 'Invoice', vendor: 'Aurora Cloud Services', date: '3 Sep 2026', mine: false, size: '188 KB', ret: '7 yr', enc: 'AES-256' },
    { n: 'Kestrel Maintenance — Bank change form', dt: 'DT-20', type: 'Contract', vendor: 'Kestrel Maintenance Co', date: '2 Sep 2026', mine: false, size: '96 KB', ret: '10 yr', enc: 'AES-256' },
    { n: 'Nexform Industrial Supply — Invoice', dt: 'DT-02', type: 'Invoice', vendor: 'Nexform Industrial Supply', date: '2 Sep 2026', mine: false, size: '204 KB', ret: '7 yr', enc: 'AES-256' },
    { n: 'Per-diem claim — Perth site visits', dt: 'DT-11', type: 'Claim', vendor: 'Internal', date: '29 Aug 2026', mine: true, size: '74 KB', ret: '5 yr', enc: 'AES-256' },
    { n: 'Advance acquittal — Adelaide summit', dt: 'DT-13', type: 'Claim', vendor: 'Internal', date: '26 Aug 2026', mine: true, size: '131 KB', ret: '5 yr', enc: 'AES-256' },
    { n: 'BlueLine Logistics — Freight receipt', dt: 'DT-09', type: 'Receipt', vendor: 'BlueLine Logistics', date: '24 Aug 2026', mine: true, size: '58 KB', ret: '5 yr', enc: 'AES-256' },
    { n: 'Meridian Facilities — Service contract', dt: 'DT-19', type: 'Contract', vendor: 'Meridian Facilities Group', date: '18 Aug 2026', mine: false, size: '1.2 MB', ret: '10 yr', enc: 'AES-256' },
    { n: 'Tessera Packaging — Purchase order', dt: 'DT-04', type: 'Invoice', vendor: 'Tessera Packaging', date: '14 Aug 2026', mine: false, size: '92 KB', ret: '7 yr', enc: 'AES-256' },
    { n: 'Corporate card statement — Aug 2026', dt: 'DT-14', type: 'Receipt', vendor: 'Internal', date: '31 Aug 2026', mine: true, size: '340 KB', ret: '7 yr', enc: 'AES-256' }
  ],
  fileFilters: ['Mine', 'Invoices', 'Receipts', 'Contracts', 'Claims', 'This month']
};
