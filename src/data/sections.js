export const lifecycleSteps = [
  { n: '01', title: 'Received', desc: 'Email, OneDrive, WhatsApp, Viber, mobile, or web. Every channel lands in one queue.' },
  { n: '02', title: 'Extracted', desc: 'OCR plus LLM field reconciliation. Totals, tax, line items — structured.' },
  { n: '03', title: 'Matched', desc: 'Vendor master lookup resolves aliases to a single supplier record.' },
  { n: '04', title: 'Classified', desc: 'The Rule Book assigns a ledger across five deterministic priority bands.' },
  { n: '05', title: 'Duplicate-checked', desc: 'Control C1 fingerprints every document against the prior 18 months.' },
  { n: '06', title: 'Pending approval', desc: 'Policy-driven routing to the right approver, by amount and category.' },
  { n: '07', title: 'Approved', desc: 'Document is frozen. The audit trail is immutable.' },
  { n: '08', title: 'Three-way matched', desc: 'PO, GRN, and Invoice quantities and prices verified.' },
  { n: '09', title: 'Payment queued', desc: 'Only approved, unflagged, matched invoices qualify (C2).' },
  { n: '10', title: 'Payment approved', desc: 'Multi-tier approval chain scaled to amount. SoD enforced (C4, C5).' },
  { n: '11', title: 'Scheduled', desc: 'Approved payment queued for execution on the chosen date.' },
  { n: '12', title: 'Paid', desc: 'Payment executed via Stripe wallet. Journal entry created.' },
  { n: '13', title: 'Posted', desc: 'Written to Xero, QuickBooks, MYOB, NetSuite, Tally, or Zoho.' },
  { n: '14', title: 'Reconciled', desc: 'A daily batch proves Δ = 0 across debits, credits, invoices, and payments.' },
];

export const controls = [
  { code: 'C1', title: 'Duplicate Prevention', desc: 'Fingerprints every inbound document against the last 18 months.', blocks: 'Blocks duplicate invoices', accent: 'blue' },
  { code: 'C2', title: 'Approved-Only Payment', desc: 'Only invoices with status=approved AND flag=clear can enter the payment queue.', blocks: 'Blocks payments to unapproved invoices', accent: 'sky' },
  { code: 'C3', title: 'Three-Way Match', desc: 'PO + GRN + Invoice must reconcile on quantity and price within tolerance.', blocks: 'Blocks variance fraud', accent: 'indigo' },
  { code: 'C4', title: 'Multi-Tier Approval', desc: 'Approver count scales with amount: 1 (<$1k), 2 ($1k–$10k), 3 ($10k–$50k), 4 (>$50k).', blocks: 'Blocks unilateral high-value payments', accent: 'blue' },
  { code: 'C5', title: 'Segregation of Duties', desc: 'The user who approves an invoice cannot also approve its payment.', blocks: 'Blocks self-dealing', accent: 'cyan' },
  { code: 'C6', title: 'Append-Only Audit', desc: 'Every state change is signed, timestamped, and immutable.', blocks: 'Blocks evidence tampering', accent: 'sky' },
];

export const captureChannels = [
  { name: 'WhatsApp', action: 'Tradesman sends receipt photo to +61 ledger number', share: '45% of v4 claims' },
  { name: 'Viber', action: 'Site supervisor forwards bill to project Viber group', share: '28% of v4 claims' },
  { name: 'Mobile app', action: 'Office manager uploads from iOS/Android', share: '17% of v4 claims' },
  { name: 'Web portal', action: 'Remote staff submits via Ledgerline web', share: '10% of v4 claims' },
];

export const procurementRules = [
  {
    id: 'quantity',
    name: 'Match · Quantity',
    desc: 'PO, GRN, and invoice quantities compared within 2% tolerance. A mismatch stops payment cold.',
    rule: 'IF |grn.qty - invoice.qty| / po.qty ≤ 0.02 → match',
    opacity: 1,
  },
  {
    id: 'price',
    name: 'Match · Price',
    desc: 'Unit price variance checked against the PO within 3%. Over-tolerance lines are flagged before approval.',
    rule: 'IF |invoice.price - po.price| / po.price ≤ 0.03 → match',
    opacity: 0.75,
  },
  {
    id: 'variance',
    name: 'Variance · Routing',
    desc: 'When quantity or price fails tolerance, the document routes to buyer and finance — never auto-approved.',
    rule: 'ELSE → flag = "variance" AND route = "buyer + finance"',
    opacity: 0.5,
  },
];

export const ruleBookBands = [
  {
    n: '1',
    name: 'Exact vendor override',
    rule: 'IF vendor.id = "AWS-AU" → ledger = "Cloud Infrastructure"',
    headerLabel: 'Priority band',
    headerValue: 'Highest',
    points: ['Vendor ID exact match', 'Overrides all lower bands', 'Ledger assigned instantly'],
    opacity: 1,
  },
  {
    n: '2',
    name: 'Alias contains',
    rule: 'IF vendor.aliases CONTAINS "Telstra" → ledger = "Telecommunications"',
    headerLabel: 'Priority band',
    headerValue: 'High',
    points: ['Fuzzy alias lookup', 'Contains-text matching', 'Handles subsidiaries'],
    opacity: 0.8,
  },
  {
    n: '3',
    name: 'Category keyword',
    rule: 'IF line.text MATCHES /freight|courier/ → ledger = "Logistics"',
    headerLabel: 'Priority band',
    headerValue: 'Medium',
    points: ['Line-item text scan', 'Regex pattern match', 'Freight & logistics default'],
    opacity: 0.62,
  },
  {
    n: '4',
    name: 'Amount threshold',
    rule: 'IF total > 10000 AUD → route = "CFO approval"',
    headerLabel: 'Priority band',
    headerValue: 'Conditional',
    points: ['Total amount check', 'Routes to CFO approval', 'AUD threshold enforced'],
    opacity: 0.46,
  },
  {
    n: '5',
    name: 'Fallback band',
    rule: 'ELSE → ledger = "Suspense" AND flag = "review"',
    headerLabel: 'Priority band',
    headerValue: 'Fallback',
    points: ['Catch-all ELSE rule', 'Suspense ledger assign', 'Flags for manual review'],
    opacity: 0.34,
  },
];

export const paymentFeatures = [
  'Single Stripe Connect wallet · top up by card, ACH, or PayID',
  'Multi-tier approval chains scaled to amount band',
  'Segregation of duties: invoice approver ≠ payment approver',
  'Schedule payments for the optimal date — never early',
  'Idempotent execution · zero double-pays even on network retry',
  'Failed payments auto-route to the queue with a reason',
];

export const entities = [
  { name: 'Acme Hospitality', tag: 'AU · AUD · GST 10%', total: '38,192.00', sym: '$' },
  { name: 'Northwind Tech', tag: 'US · USD · Sales Tax', total: '21,540.00', sym: '$' },
  { name: 'Bharat Manufacturing', tag: 'IN · INR · GST 18%', total: '14,86,200.00', sym: '₹' },
];

export const integrations = [
  'Xero', 'QuickBooks', 'MYOB', 'NetSuite', 'SAP', 'Tally', 'Zoho',
  'Stripe Connect', 'WhatsApp', 'Viber', 'Microsoft 365', 'Google Drive',
  'Slack', 'Oracle', 'Zapier', 'Plaid',
];

export const recentInvoices = [
  { id: 'INV-4417', vendor: 'Amazon Web Services', amt: '4,182.00', ledger: 'Cloud Infrastructure', state: 'Posted' },
  { id: 'INV-4416', vendor: 'Telstra Corporation', amt: '612.40', ledger: 'Telecommunications', state: 'Posted' },
  { id: 'INV-4415', vendor: 'Officeworks', amt: '289.95', ledger: 'Office Supplies', state: 'Approved' },
];
