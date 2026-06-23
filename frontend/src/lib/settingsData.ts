/** Settings page constants — aligned with Ledgerline v3 prototype. */

export type CountryOption = {
  code: string;
  name: string;
  currency: string;
  symbol: string;
  locale: string;
  timeZone: string;
  taxRate: number;
  taxLabel: string;
  dialCode: string;
};

export type ChartOfAccountRow = {
  code: string;
  name: string;
  type: "Expense" | "Asset" | "Liability";
};

export type TeamMemberRow = {
  id: string;
  name: string;
  email: string;
  role: string;
};

export const INDUSTRIES = [
  "Hospitality",
  "Technology",
  "Retail",
  "Manufacturing",
  "Healthcare",
  "Professional Services",
  "Construction",
  "Other",
] as const;

export const COUNTRIES: CountryOption[] = [
  {
    code: "AU",
    name: "Australia",
    currency: "AUD",
    symbol: "A$",
    locale: "en-AU",
    timeZone: "Australia/Sydney",
    taxRate: 10,
    taxLabel: "GST",
    dialCode: "+61",
  },
  {
    code: "US",
    name: "United States",
    currency: "USD",
    symbol: "$",
    locale: "en-US",
    timeZone: "America/New_York",
    taxRate: 8.5,
    taxLabel: "Sales Tax",
    dialCode: "+1",
  },
  {
    code: "GB",
    name: "United Kingdom",
    currency: "GBP",
    symbol: "£",
    locale: "en-GB",
    timeZone: "Europe/London",
    taxRate: 20,
    taxLabel: "VAT",
    dialCode: "+44",
  },
  {
    code: "IN",
    name: "India",
    currency: "INR",
    symbol: "₹",
    locale: "en-IN",
    timeZone: "Asia/Kolkata",
    taxRate: 18,
    taxLabel: "GST",
    dialCode: "+91",
  },
  {
    code: "SG",
    name: "Singapore",
    currency: "SGD",
    symbol: "S$",
    locale: "en-SG",
    timeZone: "Asia/Singapore",
    taxRate: 9,
    taxLabel: "GST",
    dialCode: "+65",
  },
  {
    code: "NZ",
    name: "New Zealand",
    currency: "NZD",
    symbol: "NZ$",
    locale: "en-NZ",
    timeZone: "Pacific/Auckland",
    taxRate: 15,
    taxLabel: "GST",
    dialCode: "+64",
  },
  {
    code: "AE",
    name: "United Arab Emirates",
    currency: "AED",
    symbol: "د.إ",
    locale: "ar-AE",
    timeZone: "Asia/Dubai",
    taxRate: 5,
    taxLabel: "VAT",
    dialCode: "+971",
  },
  {
    code: "DE",
    name: "Germany",
    currency: "EUR",
    symbol: "€",
    locale: "de-DE",
    timeZone: "Europe/Berlin",
    taxRate: 19,
    taxLabel: "VAT",
    dialCode: "+49",
  },
];

export const CHART_OF_ACCOUNTS: ChartOfAccountRow[] = [
  { code: "5010", name: "Cloud Hosting Expense", type: "Expense" },
  { code: "5020", name: "Software Subscription Expense", type: "Expense" },
  { code: "5030", name: "Marketing Expense", type: "Expense" },
  { code: "5040", name: "Professional Services Expense", type: "Expense" },
  { code: "5050", name: "Travel Expense", type: "Expense" },
  { code: "5060", name: "R&D Expense", type: "Expense" },
  { code: "5070", name: "Raw Materials", type: "Expense" },
  { code: "5080", name: "Logistics", type: "Expense" },
  { code: "1310", name: "GST Paid", type: "Asset" },
  { code: "2010", name: "Accounts Payable", type: "Liability" },
  { code: "9999", name: "Suspense Account", type: "Liability" },
];

export function countryByCode(code: string): CountryOption {
  return COUNTRIES.find((c) => c.code === code) ?? COUNTRIES[0];
}

