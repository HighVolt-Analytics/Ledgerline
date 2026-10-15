export const spectraCaseStudy = {
  slug: 'spectra',
  company: 'Spectra',
  sector: 'Export & Import Across Multiple Countries',
  heroImage: '/qll/industries/spectra-hero.jpg',
  heroPrimary: 'From scattered trade documents',
  heroSecondary: 'to audit-ready ledger posting with Quantum Ledger Line',
  resultMetric: '1',
  resultRest:
    'Commercial Invoice Number to trace the full shipment — collect, classify, validate, and post automatically',
  about:
    'Spectra operates export and import across multiple countries. With Quantum Ledger Line, their accounting team turns unstructured trade documents into structured ledger workflows — organized for compliance and audit.',
  storySections: [
    {
      label: 'Executive Summary',
      paragraphs: [
        'The client needed a system that collates documents from various channels such as email and WhatsApp.',
        'It understands, classifies, extracts, processes, approves, posts entries, and provides hands-off in exceptional cases for human-in-the-loop — and bundles based on document lineage.',
        'Also, design a learning loop that understands documents on its own, through human-in-the-loop, and does posting based on a deterministic approach.',
        'And have a document management system where all the priority documents are organized for compliance and audit purposes.',
        'The challenges were each shipment having several documents flowing from different stakeholders at different times and geographical locations. Sometimes the documents were in different languages, currencies, and did not have a clear lineage.',
      ],
      bullets: [
        'Certificates of Origin',
        'Import License',
        'Purchase Orders',
        'Proforma Invoices',
        'Bills of Lading',
        'Airway Bills',
        'Packing Lists',
        'GRNs',
        'Commercial Invoices',
        'Payment Advice',
      ],
    },
    {
      label: 'Executive Summary',
      paragraphs: [
        'They arrived through emails, scanned copies, PDFs, and sometimes even handwritten documents. Many contained multiple pages having 20–30 line items.',
        'Transactions involved multiple currencies, including USD and SGD. But accounting required everything to be declared in SGD.',
        'When auditors asked for shipment records, teams spent hours searching, matching, and verifying documents.',
        'The client wanted one system that could understand the entire transaction.',
        "That's where Quantum Ledger Line came in.",
      ],
    },
    {
      label: "Client's Ask",
      paragraphs: [
        'They clearly mentioned they already had a document storage platform.',
        "But the existing platform was incapable of meeting the client's requirement.",
        'They wanted a system that could accept documents from multiple sources.',
        'Understand what each document was.',
        'Group related documents into one transaction.',
        'Validate the numbers.',
        'And post the transaction into the correct ledger.',
        'Everything without manual sorting.',
      ],
    },
    {
      label: 'Why This Matters',
      paragraphs: [
        'International trade depends on documentation.',
        'A single missing document can delay audits, reconciliation, and financial reporting.',
        'As shipment volumes increased, so did document complexity.',
        "Manual organization wasn't scalable anymore.",
        'The business needed automation that could work with real-world documents — not perfectly formatted templates.',
      ],
    },
    {
      label: 'The Challenge',
      paragraphs: [
        'The first version of our solution worked well on standard documents.',
        'But production exposed a different reality.',
        'Some files contained multiple documents inside a single PDF.',
        'Some invoices were handwritten.',
        'Others arrived in completely different formats from suppliers across countries.',
        'Many documents referred to the same shipment but never referenced each other directly.',
        'Currency conversion added another layer of complexity.',
        'Building a system that could understand these relationships took months of testing.',
        'Especially when the documents were incomplete, unclear, or disconnected.',
      ],
    },
    {
      label: 'The Quantum Ledger Line Approach',
      paragraphs: [
        'Quantum Ledger Line became the first step in the accounting workflow.',
        'It automatically collects documents from email.',
        'It separates PDFs containing multiple documents.',
        'It identifies every document.',
        'Then it bundles related documents using the Commercial Invoice Number.',
        'The system compares the Purchase Order, Commercial Invoice and GRN.',
        'Any mismatch is immediately flagged for review.',
        'Once validated, the transaction is posted into the appropriate ledger.',
        'The entire process happens automatically.',
      ],
    },
    {
      label: 'Business Impact',
      paragraphs: [
        'Accounting teams no longer spend hours organizing trade documents.',
        'Auditors can trace the complete transaction from a single Commercial Invoice Number.',
        'Document matching happens automatically.',
        'Variances are identified before posting.',
        'Ledger entries become faster and more consistent.',
        'Instead of managing paperwork, finance teams can focus on financial control and decision-making.',
      ],
    },
    {
      label: 'Looking Ahead',
      paragraphs: [
        'For the client, this is more than document automation.',
        'It is the foundation for intelligent accounting.',
        'As Quantum Ledger Line continues learning from real trade documents, it will handle increasingly complex transactions across suppliers, countries, and currencies.',
        'The long-term objective remains unchanged.',
        'Turning unstructured documents into structured business workflows.',
        'So organizations can scale with global growth.',
      ],
    },
  ],
};

export function spectraStoryTitle() {
  return `${spectraCaseStudy.company} case study — Quantum Ledger Line`;
}

export function spectraStoryDescription() {
  return spectraCaseStudy.resultRest;
}
