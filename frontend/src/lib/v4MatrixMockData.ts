export type MatrixFlagType =
  | "Clean"
  | "Anomaly Detected"
  | "Duplicate Suspected"
  | "Quarantined";

export type MatrixPaymentStatus =
  | "Paid"
  | "Awaiting Payment"
  | "Payment Approved"
  | "On Hold"
  | "Failed"
  | "—";

export type MatrixConflictRow = {
  field: string;
  thisDoc: string;
  otherDoc: string;
};

export type MatrixFlagEntry = {
  docId: string;
  flag: Exclude<MatrixFlagType, "Clean" | "Quarantined">;
  reason: string;
  paymentStatus?: MatrixPaymentStatus;
  conflictWith?: string;
  conflictDetail?: MatrixConflictRow[];
};

/** v4 `MW` — demo matrix flags keyed by document id (INV-00n). */
export const V4_MATRIX_FLAGS: MatrixFlagEntry[] = [
  {
    docId: "INV-003",
    flag: "Anomaly Detected",
    reason:
      "Total deviates +52% from Google Australia 90-day median ($3,520). Marketing spend spike flagged for review.",
    paymentStatus: "On Hold",
  },
  {
    docId: "INV-009",
    flag: "Anomaly Detected",
    reason:
      "Vendor on hold (James Patel Consulting) and routed to Suspense — GL mapping unresolved.",
    paymentStatus: "—",
  },
  {
    docId: "INV-007",
    flag: "Anomaly Detected",
    reason:
      "Invoice date is 196 days older than received date — possible back-dated document.",
    paymentStatus: "Awaiting Payment",
  },
  {
    docId: "INV-008",
    flag: "Duplicate Suspected",
    reason:
      "Matches 2 of 4 identity keys with INV-001 (vendor cloud category + total within ±$0.10).",
    conflictWith: "INV-001",
    conflictDetail: [
      { field: "Vendor category", thisDoc: "Cloud Hosting (Azure)", otherDoc: "Cloud Hosting (AWS)" },
      { field: "Line-item hash", thisDoc: "9f2a·compute+storage", otherDoc: "9f2a·compute+storage" },
      { field: "Total", thisDoc: "A$2,288.00", otherDoc: "A$3,113.00" },
      { field: "Invoice number", thisDoc: "MSFT-AZ-AU-77192", otherDoc: "AWS-AU-204815" },
    ],
    paymentStatus: "On Hold",
  },
  {
    docId: "INV-006",
    flag: "Duplicate Suspected",
    reason:
      "Matches 2 of 4 identity keys with a prior Qantas booking (same vendor + invoice number stem QF-BOOK).",
    conflictWith: "INV-007",
    conflictDetail: [
      { field: "Vendor", thisDoc: "Qantas Airways Limited", otherDoc: "Hilton Sydney" },
      { field: "Cost centre", thisDoc: "SALES-TRAVEL", otherDoc: "SALES-TRAVEL" },
      { field: "Invoice number", thisDoc: "QF-BOOK-3318745", otherDoc: "HIL-SYD-5572" },
      { field: "Total", thisDoc: "A$2,838.00", otherDoc: "A$2,123.00" },
    ],
    paymentStatus: "—",
  },
];

/** v4 `RW` — default payment status per document when no flag override. */
export const V4_MATRIX_PAYMENTS: Record<string, MatrixPaymentStatus> = {
  "INV-001": "Paid",
  "INV-002": "Awaiting Payment",
  "INV-004": "Payment Approved",
  "INV-005": "—",
  "INV-010": "Awaiting Payment",
};

export function lookupMatrixFlag(docId: string): MatrixFlagEntry | undefined {
  return V4_MATRIX_FLAGS.find((f) => f.docId === docId);
}

export function defaultMatrixPayment(docId: string): MatrixPaymentStatus {
  return V4_MATRIX_PAYMENTS[docId] ?? "—";
}
