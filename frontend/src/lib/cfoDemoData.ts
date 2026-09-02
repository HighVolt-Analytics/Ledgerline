/** Demo tenant dataset for Dashboard prototype sections. */

export type CfoDepartment = {
  name: string;
  budget: number;
  actual: number;
  committed: number;
  owner: string;
};

export type CfoVendor = {
  name: string;
  spend: number;
  invoices: number;
  cycle: number;
  po: number;
  risk: "Low" | "Medium" | "High";
  flag?: string;
};

export type CfoAlert = {
  sev: "high" | "med" | "low";
  title: string;
  detail: string;
  meta: string;
};

export type CfoAgeingBucket = {
  bucket: string;
  value: number;
};

export const CFO_DEMO = {
  meta: {
    tenant: "Spectra Innovations Pty Ltd",
    currency: "AUD",
    period: "FY26 YTD — to 31 Aug 2026",
    generated: "22 Aug 2026, 20:30 AEST",
  },

  kpi: {
    apOutstanding: 4823400,
    due7: 1142800,
    due14: 1861200,
    due30: 2948600,
    overdue: 612300,
    overduePct: 12.7,
    approvedNotPaid: 1376900,
    dpo: 41.6,
    dpoPrior: 48.2,
    onTimeRate: 94.2,
    invoicesMTD: 1842,
    invoicesYTD: 3614,
    touchless: 78.4,
    touchlessTarget: 85,
    straightThrough: 71.2,
    costPerInvoice: 3.1,
    costBaseline: 30.0,
    avgProcMins: 3.4,
    baselineMins: 182,
    hoursSaved: 10780,
    fte: 5.9,
    dupPrevented: 427600,
    fraudEvents: 6,
    fraudAtRisk: 214900,
    discountAvailable: 52400,
    discountCaptured: 38700,
    discountRate: 73.9,
    openExceptions: 63,
    exceptionAtRisk: 1290000,
    suspenseItems: 14,
    suspenseValue: 184200,
    budgetYTD: 18600000,
    actualYTD: 17392000,
    committed: 2140000,
    utilisation: 93.5,
    claimsPending: 128,
    claimsPendingValue: 96400,
    advancesOutstanding: 312450,
    advancesOverdue: 58900,
    advancesOverdueEmployees: 9,
    cardUnsubstantiated: 41300,
    cardUnsubTxns: 68,
    vaultDocs: 46281,
    missingDocs: 214,
    pastRetention: 37,
    nonPoSpend: 22.8,
    top10Concentration: 61.4,
    syncSuccess: 99.1,
    deadLetter: 4,
    valueDelivered: 863400,
  },

  ageing: [
    { bucket: "Current", value: 3214000 },
    { bucket: "1–30 days", value: 742100 },
    { bucket: "31–60 days", value: 418600 },
    { bucket: "61–90 days", value: 268400 },
    { bucket: "90+ days", value: 180300 },
  ] satisfies CfoAgeingBucket[],

  cashWeeks: [
    "24 Aug", "31 Aug", "7 Sep", "14 Sep", "21 Sep", "28 Sep", "5 Oct",
    "12 Oct", "19 Oct", "26 Oct", "2 Nov", "9 Nov", "16 Nov",
  ],

  cashSplit: {
    confirmed: [742800, 586400, 714600, 512300, 628900, 806700, 424200, 652500, 538400, 704300, 466700, 754800, 542100],
    probable: [214000, 208000, 286000, 178000, 216000, 312000, 164000, 234000, 194000, 268000, 172000, 296000, 202000],
    recurring: [86000, 86000, 104000, 86000, 96000, 108000, 86000, 96000, 86000, 104000, 86000, 108000, 96000],
    reimbursements: [54000, 62000, 58000, 48000, 56000, 64000, 46000, 62000, 52000, 62000, 46000, 62000, 56000],
    advances: [16000, 12000, 18000, 12000, 16000, 22000, 14000, 18000, 12000, 18000, 12000, 18000, 14000],
    tax: [30000, 32000, 34000, 36000, 36000, 14000, 30000, 30000, 36000, 28000, 24000, 26000, 32000],
  },

  cashMeta: [
    { balance: 6420000 }, { balance: 5980000 }, { balance: 5410000 }, { balance: 5120000 },
    { balance: 4860000 }, { balance: 4390000 }, { balance: 4210000 }, { balance: 3980000 },
    { balance: 3840000 }, { balance: 3610000 }, { balance: 3520000 }, { balance: 3280000 },
    { balance: 3190000 },
  ],

  cashSummary: {
    nextWeek: 1142800,
    total13Week: 13564700,
    peakWeek: 1326700,
    peakLabel: "w/c 28 Sep",
    coverageRatio: 5.6,
  },

  departments: [
    { name: "Operations", budget: 6400000, actual: 6118000, committed: 780000, owner: "D. Okafor" },
    { name: "Technology", budget: 4200000, actual: 4486000, committed: 610000, owner: "J. Whitfield" },
    { name: "Sales & Marketing", budget: 2900000, actual: 2614000, committed: 240000, owner: "P. Raman" },
    { name: "Logistics", budget: 2300000, actual: 2208000, committed: 320000, owner: "M. L. Tan" },
    { name: "Corporate & Admin", budget: 1600000, actual: 1394000, committed: 110000, owner: "S. Almeida" },
    { name: "People & Culture", budget: 1200000, actual: 572000, committed: 80000, owner: "G. Nakamura" },
  ] satisfies CfoDepartment[],

  vendors: [
    { name: "Pacific Freight Holdings", spend: 2140000, invoices: 312, cycle: 4.2, po: 96, risk: "Low" },
    { name: "Nexform Industrial Supply", spend: 1684000, invoices: 208, cycle: 5.1, po: 91, risk: "Low" },
    { name: "Aurora Cloud Services", spend: 1392000, invoices: 24, cycle: 2.8, po: 40, risk: "Medium" },
    { name: "Meridian Facilities Group", spend: 986000, invoices: 144, cycle: 6.4, po: 88, risk: "Low" },
    { name: "BlueLine Logistics", spend: 842000, invoices: 176, cycle: 3.9, po: 93, risk: "Low" },
    { name: "Tessera Packaging", spend: 731000, invoices: 98, cycle: 7.2, po: 79, risk: "Medium" },
    { name: "Halcyon Legal Advisory", spend: 604000, invoices: 36, cycle: 9.8, po: 0, risk: "Medium" },
    { name: "Orbit Staffing Solutions", spend: 588000, invoices: 62, cycle: 5.6, po: 84, risk: "Low" },
    { name: "Vertex Energy Retail", spend: 471000, invoices: 12, cycle: 3.1, po: 0, risk: "Low" },
    {
      name: "Kestrel Maintenance Co",
      spend: 402000,
      invoices: 88,
      cycle: 6.8,
      po: 90,
      risk: "High",
      flag: "Bank detail change flagged",
    },
  ] satisfies CfoVendor[],

  alerts: [
    { sev: "high", title: "Vendor bank detail change — Kestrel Maintenance Co", detail: "Change requested 20 Aug. Out-of-band callback pending. 84,200 held.", meta: "Control: Bank change verification" },
    { sev: "high", title: "Technology over budget", detail: "Actual 4,486,000 vs budget 4,200,000 — 106.8% utilised, 610,000 committed on open PO.", meta: "Owner: J. Whitfield" },
    { sev: "high", title: "Advance overdue beyond policy", detail: "58,900 across 9 employees. Oldest: T. Berger, 74 days.", meta: "Recovery: payroll deduction proposed" },
    { sev: "med", title: "Overdue AP at 12.7%", detail: "612,300 overdue; 180,300 in the 90+ bucket concentrated in 3 disputed vendors.", meta: "Threshold: 10%" },
    { sev: "med", title: "Unsubstantiated card spend", detail: "41,300 over 68 transactions; 12,400 ageing beyond 30 days.", meta: "Threshold: 25,000" },
    { sev: "med", title: "Exception queue ageing", detail: "63 open exceptions, 1,290,000 at risk. 9 items older than 5 days.", meta: "SLA: 5 days" },
    { sev: "low", title: "Touchless rate below target", detail: "78.4% vs 85% target. Non-PO invoice intake is the main drag.", meta: "Trend: +2.1 pts MoM" },
    { sev: "low", title: "Xero dead-letter queue", detail: "4 items failed after 5 attempts — attachment size and contact mismatch.", meta: "Sync success 99.1%" },
  ] satisfies CfoAlert[],

  dpoTrend: {
    labels: ["Sep 25", "Oct 25", "Nov 25", "Dec 25", "Jan 26", "Feb 26", "Mar 26", "Apr 26", "May 26", "Jun 26", "Jul 26", "Aug 26"],
    dpo: [48.2, 47.4, 46.8, 46.1, 45.2, 44.6, 44.0, 43.4, 42.8, 42.3, 41.9, 41.6],
    touchless: [58.2, 60.4, 62.8, 64.1, 66.9, 68.4, 70.6, 72.2, 74.1, 75.8, 77.0, 78.4],
  },

  apAgeingTotal: 4823400,
  vendorConcentration: { top10Pct: 61.4, nonPoSpend: 22.8, contractedOf10: 7, highRiskCount: 1 },
} as const;
