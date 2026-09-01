/** Bank feeds UI gates — keep in sync with backend feature_flags.py intent. */
export const BANK_FEEDS_TRANSFER_ENABLED = false;

/** Accepted bank statement upload formats (UI + client validation). */
export const BANK_FEED_IMPORT_ACCEPT = ".pdf,.csv,application/pdf,text/csv";

export const BANK_FEED_IMPORT_FORMAT_HINT = "PDF or CSV · 10 MB max";

export const BANK_FEED_IMPORT_DROP_LABEL = "Drop a bank statement (PDF or CSV) or browse";

export const BANK_FEED_IMPORT_BROWSE_LABEL = "Browse statement";
