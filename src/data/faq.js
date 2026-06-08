export const faqItems = [
  {
    q: 'Does Ledgerline actually pay invoices, or just file them?',
    a: 'v4 pays them. Approved invoices flow into a Stripe Connect wallet you top up once. Multi-tier approval runs over the amount band, segregation of duties is enforced server-side, and the wire executes on the scheduled date — with the journal entry posted simultaneously.',
  },
  {
    q: 'How do you prevent duplicate invoices?',
    a: 'Control C1 fingerprints every inbound document — vendor ID, invoice number, amount, date, line-item hash — against the prior 18 months. Duplicates are quarantined the moment they arrive.',
  },
  {
    q: 'What stops one person from approving and paying an invoice they raised?',
    a: 'Control C5 — Segregation of Duties. The system enforces that the invoice approver and the payment approver must be different users. There is no admin override.',
  },
  {
    q: 'How do team members submit claims from the field?',
    a: 'They send a photo of the receipt to a WhatsApp or Viber number — Ledgerline OCRs it, classifies the ledger, and queues it for the approver.',
  },
  {
    q: 'Is my accounting data secure?',
    a: 'Every document is encrypted in transit and at rest. Each org is isolated at the storage layer, and approved entries are frozen with an immutable audit trail.',
  },
  {
    q: 'Do I need to change my accounting software?',
    a: 'No. Ledgerline posts into Xero, QuickBooks, MYOB, or NetSuite using their native APIs. If you prefer, it exports a clean CSV journal instead.',
  },
  {
    q: 'How accurate is the OCR and extraction?',
    a: 'First-pass classification accuracy sits above 95%, with LLM field reconciliation cross-checking totals, tax, and line items against the vendor master.',
  },
  {
    q: "What happens to invoices that don't match a rule?",
    a: 'They fall to Band 5 — the fallback — which posts to a Suspense ledger and flags the document for review.',
  },
  {
    q: 'Can my team approve from email?',
    a: 'Yes. Policy-driven routing sends each approval to the right person by amount and category. They approve inline from email or the dashboard.',
  },
  {
    q: 'Does it work outside Australia?',
    a: 'Yes. Ledgerline is multi-currency and multi-tax by design. Each org carries its own currency, tax regime, and ledger map under one login.',
  },
];
