import type { InvoiceDetails, JournalEntry, ReconciliationOverview, RuleBook } from "@/api/types";
import { documentDisplayRef } from "@/lib/format";
import {
  DEFAULT_TENANT_LOCALE,
  tenantMonthKey,
  tenantZonedParts,
} from "@/lib/tenantTime";

export type ReconPosting = {
  account: string;
  debit: number;
  credit: number;
};

export type ReconInvoiceRow = {
  id: string;
  vendor: string;
  total: number;
  postings: ReconPosting[];
};

export type ReconDay = {
  date: string;
  count: number;
  sumDr: number;
  sumCr: number;
  delta: number;
  invoices: ReconInvoiceRow[];
};

export type ReconSummary = {
  sumTotals: number;
  sumDr: number;
  sumCr: number;
  deltaDrCr: number;
  balanced: boolean;
  byDate: ReconDay[];
};

export type MockSampleLine = {
  description: string;
  qty: number;
  unit_price: number;
};

export type MockSampleInvoice = {
  id: string;
  vendor: string;
  invoice_date: string;
  po?: string;
  lines: MockSampleLine[];
};

/** v3 sample documents (Gz array). */
export const V3_SAMPLE_INVOICES: MockSampleInvoice[] = [
  {
    id: "INV-001",
    vendor: "Amazon Web Services",
    invoice_date: "2026-05-02",
    lines: [
      { description: "EC2 Compute - May 2026", qty: 1, unit_price: 2450 },
      { description: "S3 Storage & Data Transfer", qty: 1, unit_price: 380 },
    ],
  },
  {
    id: "INV-002",
    vendor: "Atlassian Pty Ltd",
    invoice_date: "2026-05-04",
    lines: [
      { description: "Jira Software Cloud - Annual Subscription (20 users)", qty: 20, unit_price: 89.5 },
      { description: "Confluence Cloud - Annual Subscription (20 users)", qty: 20, unit_price: 55 },
    ],
  },
  {
    id: "INV-003",
    vendor: "Google Australia Pty Ltd",
    invoice_date: "2026-05-06",
    po: "PO-MKT-2026-014",
    lines: [
      { description: "Google Ads - Search Campaign May", qty: 1, unit_price: 4200 },
      { description: "Google Ads - Display Network May", qty: 1, unit_price: 1150 },
    ],
  },
  {
    id: "INV-004",
    vendor: "Meta Platforms Ireland",
    invoice_date: "2026-05-08",
    po: "PO-MKT-2026-014",
    lines: [
      { description: "Facebook Ads - Lead Generation Campaign", qty: 1, unit_price: 1850 },
      { description: "Instagram Ads - Awareness Campaign", qty: 1, unit_price: 950 },
    ],
  },
  {
    id: "INV-005",
    vendor: "Deloitte Touche Tohmatsu",
    invoice_date: "2026-05-11",
    lines: [
      { description: "R&D Tax Incentive Consulting - May 2026", qty: 12, unit_price: 450 },
      { description: "Advisory Workshop - Compliance Review", qty: 1, unit_price: 2200 },
    ],
  },
  {
    id: "INV-006",
    vendor: "Qantas Airways Limited",
    invoice_date: "2026-05-13",
    lines: [
      { description: "Flights SYD-MEL Return - 3 passengers", qty: 3, unit_price: 540 },
      { description: "Flights SYD-BNE Return - 2 passengers", qty: 2, unit_price: 480 },
    ],
  },
  {
    id: "INV-007",
    vendor: "Hilton Sydney",
    invoice_date: "2026-05-14",
    lines: [
      { description: "Hotel Accommodation - 4 nights Executive Room", qty: 4, unit_price: 320 },
      { description: "Conference Room Hire - Half Day", qty: 1, unit_price: 650 },
    ],
  },
  {
    id: "INV-008",
    vendor: "Microsoft Azure",
    invoice_date: "2026-05-18",
    lines: [
      { description: "Azure Cloud Compute - May 2026", qty: 1, unit_price: 1820 },
      { description: "Azure Blob Storage - May 2026", qty: 1, unit_price: 260 },
    ],
  },
  {
    id: "INV-009",
    vendor: "James Patel Consulting",
    invoice_date: "2026-05-21",
    po: "PO-RND-2026-007",
    lines: [
      { description: "Freelance Backend Development - Sprint 14", qty: 38, unit_price: 140 },
      { description: "Freelance Code Review & Advisory", qty: 6, unit_price: 140 },
    ],
  },
  {
    id: "INV-010",
    vendor: "Sydney Office Florals Pty Ltd",
    invoice_date: "2026-05-25",
    lines: [
      { description: "Weekly Office Floral Arrangement - May", qty: 4, unit_price: 95 },
      { description: "Reception Plant Maintenance", qty: 1, unit_price: 120 },
    ],
  },
];

export function roundMoney(n: number): number {
  return Math.round(n * 100) / 100;
}

function toNum(v: string | number | null | undefined): number {
  if (v == null || v === "") return 0;
  const n = typeof v === "string" ? parseFloat(v) : v;
  return Number.isNaN(n) ? 0 : n;
}

/** v3 line-level rule match (PO → vendor → keyword on description → fallback). */
export function mapLineAccount(
  invoice: MockSampleInvoice,
  line: MockSampleLine,
  book: RuleBook
): string {
  if (invoice.po && book.po_codes[invoice.po]) return book.po_codes[invoice.po];
  if (book.vendors[invoice.vendor]) return book.vendors[invoice.vendor];
  const haystack = line.description.toLowerCase();
  const sorted = Object.entries(book.keywords).sort(([a], [b]) => b.length - a.length);
  for (const [keyword, account] of sorted) {
    if (haystack.includes(keyword.toLowerCase())) return account;
  }
  return book.fallback_account;
}

export function buildPostingsForMockInvoice(
  invoice: MockSampleInvoice,
  book: RuleBook,
  taxRate = 0.1
): { total: number; postings: ReconPosting[] } {
  let subtotal = 0;
  const postings: ReconPosting[] = [];

  for (const line of invoice.lines) {
    const lineSubtotal = roundMoney(line.qty * line.unit_price);
    subtotal = roundMoney(subtotal + lineSubtotal);
    postings.push({
      account: mapLineAccount(invoice, line, book),
      debit: lineSubtotal,
      credit: 0,
    });
  }

  const gst = roundMoney(subtotal * taxRate);
  const total = roundMoney(subtotal + gst);

  postings.push({ account: book.tax_account, debit: gst, credit: 0 });
  postings.push({ account: book.payable_account, debit: 0, credit: total });

  return { total, postings };
}

export function buildReconciliationFromMock(
  samples: MockSampleInvoice[],
  book: RuleBook,
  taxRate = 0.1
): ReconSummary {
  const rows = samples.map((inv) => {
    const { total, postings } = buildPostingsForMockInvoice(inv, book, taxRate);
    return {
      id: inv.id,
      vendor: inv.vendor,
      invoice_date: inv.invoice_date,
      total,
      postings,
    };
  });
  return buildReconciliation(rows);
}

function journalToPostings(entries: JournalEntry[]): ReconPosting[] {
  return entries.map((e) => ({
    account: e.account_name || e.account_code,
    debit: toNum(e.debit),
    credit: toNum(e.credit),
  }));
}

export function buildReconciliationFromApiInvoices(
  invoices: InvoiceDetails[]
): ReconSummary {
  const rows = invoices
    .filter((inv) => inv.journal_entries.length > 0 && inv.invoice_date)
    .map((inv) => ({
      id: documentDisplayRef(inv),
      vendor: inv.vendor ?? "—",
      invoice_date: inv.invoice_date!,
      total: toNum(inv.total),
      postings: journalToPostings(inv.journal_entries),
    }));
  return buildReconciliation(rows);
}

export function mapReconciliationOverview(data: ReconciliationOverview): ReconSummary {
  const byDate: ReconDay[] = data.by_date.map((day) => ({
    date: day.date,
    count: day.count,
    sumDr: toNum(day.sum_dr),
    sumCr: toNum(day.sum_cr),
    delta: toNum(day.delta),
    invoices: day.invoices.map((inv) => ({
      id: inv.id,
      vendor: inv.vendor,
      total: toNum(inv.total),
      postings: inv.postings.map((p) => ({
        account: p.account,
        debit: toNum(p.debit),
        credit: toNum(p.credit),
      })),
    })),
  }));

  return {
    sumTotals: toNum(data.sum_totals),
    sumDr: toNum(data.sum_dr),
    sumCr: toNum(data.sum_cr),
    deltaDrCr: toNum(data.delta_dr_cr),
    balanced: data.balanced,
    byDate,
  };
}

type ReconSourceRow = {
  id: string;
  vendor: string;
  invoice_date: string;
  total: number;
  postings: ReconPosting[];
};

export function buildReconciliation(rows: ReconSourceRow[]): ReconSummary {
  let sumTotals = 0;
  let sumDr = 0;
  let sumCr = 0;
  const byDateMap = new Map<string, ReconDay>();

  for (const row of rows) {
    const rowDr = roundMoney(row.postings.reduce((s, p) => s + p.debit, 0));
    const rowCr = roundMoney(row.postings.reduce((s, p) => s + p.credit, 0));

    sumTotals = roundMoney(sumTotals + row.total);
    sumDr = roundMoney(sumDr + rowDr);
    sumCr = roundMoney(sumCr + rowCr);

    const date = row.invoice_date;
    if (!byDateMap.has(date)) {
      byDateMap.set(date, {
        date,
        count: 0,
        sumDr: 0,
        sumCr: 0,
        delta: 0,
        invoices: [],
      });
    }
    const day = byDateMap.get(date)!;
    day.count += 1;
    day.sumDr = roundMoney(day.sumDr + rowDr);
    day.sumCr = roundMoney(day.sumCr + rowCr);
    day.delta = roundMoney(day.sumDr - day.sumCr);
    day.invoices.push({
      id: row.id,
      vendor: row.vendor,
      total: row.total,
      postings: row.postings,
    });
  }

  const byDate = Array.from(byDateMap.values()).sort((a, b) =>
    a.date.localeCompare(b.date)
  );

  const deltaDrCr = roundMoney(sumDr - sumCr);
  return {
    sumTotals,
    sumDr,
    sumCr,
    deltaDrCr,
    balanced: deltaDrCr === 0,
    byDate,
  };
}

export function monthKeyFromDate(isoDate: string): string {
  return isoDate.slice(0, 7);
}

export function formatReconMonthLabel(monthKey: string, locale = DEFAULT_TENANT_LOCALE): string {
  const [y, m] = monthKey.split("-").map(Number);
  if (!y || !m) return monthKey;
  return new Date(y, m - 1, 1).toLocaleString(locale, {
    month: "long",
    year: "numeric",
  });
}

export function formatReconMonthOnly(monthKey: string, locale = DEFAULT_TENANT_LOCALE): string {
  const [, m] = monthKey.split("-").map(Number);
  if (!m) return monthKey;
  return new Date(2020, m - 1, 1).toLocaleString(locale, { month: "long" });
}

export function yearFromPeriod(monthKey: string): string {
  return monthKey.slice(0, 4);
}

export function groupReconPeriodOptionsByYear(
  options: { label: string; value: string }[]
): { year: string; options: { label: string; value: string }[] }[] {
  const byYear = new Map<string, { label: string; value: string }[]>();
  for (const opt of options) {
    const year = opt.value.slice(0, 4);
    const list = byYear.get(year) ?? [];
    list.push(opt);
    byYear.set(year, list);
  }
  return Array.from(byYear.entries())
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([year, opts]) => ({ year, options: opts }));
}

export function reconYearsFromOptions(options: { label: string; value: string }[]): string[] {
  return groupReconPeriodOptionsByYear(options).map((g) => g.year);
}

/** All years with data, plus years touched by the rolling 12-month window and the current year. */
export function buildReconYears(recon: ReconSummary | null, timeZone: string): string[] {
  const years = new Set<string>();
  const { year } = tenantZonedParts(timeZone);
  years.add(String(year));
  for (let i = 0; i < 12; i++) {
    years.add(tenantMonthKey(timeZone, i).slice(0, 4));
  }
  if (recon) {
    for (const day of recon.byDate) {
      years.add(day.date.slice(0, 4));
    }
  }
  return Array.from(years).sort().reverse();
}

/** Calendar months for a year — current year up to today; prior years all 12 (newest first). */
export function buildMonthsForYear(
  year: string,
  timeZone: string,
  locale = DEFAULT_TENANT_LOCALE
): { label: string; value: string }[] {
  const y = Number(year);
  if (!y || Number.isNaN(y)) return [];

  const { year: currentYear, month: currentMonth } = tenantZonedParts(timeZone);

  if (y > currentYear) return [];

  const maxMonth = y === currentYear ? currentMonth : 12;

  return Array.from({ length: maxMonth }, (_, i) => {
    const month = maxMonth - i;
    const value = `${year}-${String(month).padStart(2, "0")}`;
    return { value, label: formatReconMonthOnly(value, locale) };
  });
}

export function reconMonthsForYear(
  options: { label: string; value: string }[],
  year: string,
  timeZone: string,
  locale = DEFAULT_TENANT_LOCALE
): { label: string; value: string }[] {
  void options;
  return buildMonthsForYear(year, timeZone, locale);
}

/** Rolling 12 months plus any months present in reconciliation data. */
export function buildReconPeriodOptions(
  recon: ReconSummary | null,
  timeZone: string,
  locale = DEFAULT_TENANT_LOCALE
): { label: string; value: string }[] {
  const keys = new Set<string>();
  for (let i = 0; i < 12; i++) {
    keys.add(tenantMonthKey(timeZone, i));
  }
  if (recon) {
    for (const day of recon.byDate) {
      keys.add(monthKeyFromDate(day.date));
    }
  }
  return Array.from(keys)
    .sort()
    .reverse()
    .map((value) => ({ value, label: formatReconMonthLabel(value, locale) }));
}

export function defaultReconPeriod(recon: ReconSummary | null, timeZone: string): string {
  const options = buildReconPeriodOptions(recon, timeZone);
  if (recon?.byDate.length) {
    const latest = monthKeyFromDate(recon.byDate[recon.byDate.length - 1].date);
    if (options.some((o) => o.value === latest)) return latest;
  }
  return options[0]?.value ?? "";
}

export function filterReconciliationByMonth(recon: ReconSummary, month: string): ReconSummary {
  const byDate = recon.byDate.filter((d) => d.date.startsWith(month));
  let sumTotals = 0;
  let sumDr = 0;
  let sumCr = 0;
  for (const day of byDate) {
    sumDr = roundMoney(sumDr + day.sumDr);
    sumCr = roundMoney(sumCr + day.sumCr);
    for (const inv of day.invoices) {
      sumTotals = roundMoney(sumTotals + inv.total);
    }
  }
  const deltaDrCr = roundMoney(sumDr - sumCr);
  return {
    sumTotals,
    sumDr,
    sumCr,
    deltaDrCr,
    balanced: deltaDrCr === 0,
    byDate,
  };
}

export function documentCountForRecon(recon: ReconSummary): number {
  return recon.byDate.reduce((sum, day) => sum + day.count, 0);
}
