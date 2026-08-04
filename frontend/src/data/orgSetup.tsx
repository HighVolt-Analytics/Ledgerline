/** v3 onboarding data — shared by /setup and settings. */

import type { ReactNode } from "react";
import { Select } from "@/components/ui/select";

export type CountryOption = {
  code: string;
  name: string;
  defaultCurrency: string;
  locale: string;
  taxRate: number;
  taxLabel: string;
  dialCode: string;
  /** @deprecated use defaultCurrency — kept for gradual call-site migration */
  currency?: string;
};

export type CurrencyOption = {
  code: string;
  name: string;
  symbol: string;
  decimalPlaces: number;
};

export const CURRENCIES: CurrencyOption[] = [
  { code: "AUD", name: "Australian Dollar", symbol: "A$", decimalPlaces: 2 },
  { code: "USD", name: "US Dollar", symbol: "$", decimalPlaces: 2 },
  { code: "GBP", name: "British Pound", symbol: "£", decimalPlaces: 2 },
  { code: "INR", name: "Indian Rupee", symbol: "₹", decimalPlaces: 2 },
  { code: "SGD", name: "Singapore Dollar", symbol: "S$", decimalPlaces: 2 },
  { code: "NZD", name: "New Zealand Dollar", symbol: "NZ$", decimalPlaces: 2 },
  { code: "AED", name: "UAE Dirham", symbol: "د.إ", decimalPlaces: 2 },
  { code: "EUR", name: "Euro", symbol: "€", decimalPlaces: 2 },
];

export const COUNTRIES: CountryOption[] = [
  { code: "AU", name: "Australia", defaultCurrency: "AUD", locale: "en-AU", taxRate: 10, taxLabel: "GST", dialCode: "+61" },
  { code: "US", name: "United States", defaultCurrency: "USD", locale: "en-US", taxRate: 8.5, taxLabel: "Sales Tax", dialCode: "+1" },
  { code: "GB", name: "United Kingdom", defaultCurrency: "GBP", locale: "en-GB", taxRate: 20, taxLabel: "VAT", dialCode: "+44" },
  { code: "IN", name: "India", defaultCurrency: "INR", locale: "en-IN", taxRate: 18, taxLabel: "GST", dialCode: "+91" },
  { code: "SG", name: "Singapore", defaultCurrency: "SGD", locale: "en-SG", taxRate: 9, taxLabel: "GST", dialCode: "+65" },
  { code: "NZ", name: "New Zealand", defaultCurrency: "NZD", locale: "en-NZ", taxRate: 15, taxLabel: "GST", dialCode: "+64" },
  { code: "AE", name: "United Arab Emirates", defaultCurrency: "AED", locale: "ar-AE", taxRate: 5, taxLabel: "VAT", dialCode: "+971" },
  { code: "DE", name: "Germany", defaultCurrency: "EUR", locale: "de-DE", taxRate: 19, taxLabel: "VAT", dialCode: "+49" },
];

export const INDUSTRIES = [
  "Hospitality",
  "Technology",
  "Retail",
  "Manufacturing",
  "Healthcare",
  "Professional Services",
  "Construction",
  "Education",
  "Other",
] as const;

export type Industry = (typeof INDUSTRIES)[number];

const VAULT_FOLDERS_BY_INDUSTRY: Record<Industry, string[]> = {
  Hospitality: ["Invoices", "POs", "Receipts", "Payroll", "Contracts"],
  Technology: ["Invoices", "SaaS subscriptions", "Contractors", "Payroll", "Legal"],
  Retail: ["Invoices", "POs", "Returns", "Payroll", "Leases"],
  Manufacturing: ["Invoices", "POs", "GRNs", "Payroll", "Compliance"],
  Healthcare: ["Invoices", "Supplies", "Payroll", "Insurance", "Compliance"],
  "Professional Services": ["Invoices", "Timesheets", "Payroll", "Contracts", "Tax"],
  Construction: ["Invoices", "POs", "Subcontractors", "Payroll", "Safety"],
  Education: ["Invoices", "Grants", "Payroll", "Facilities", "Compliance"],
  Other: ["Invoices", "POs", "Receipts", "Payroll", "Contracts"],
};

export function countryByCode(code: string): CountryOption {
  return COUNTRIES.find((c) => c.code === code) ?? COUNTRIES.find((c) => c.code === "SG") ?? COUNTRIES[0];
}

export function currencyByCode(code: string): CurrencyOption {
  return (
    CURRENCIES.find((c) => c.code === code) ??
    CURRENCIES.find((c) => c.code === "SGD") ??
    CURRENCIES[0]
  );
}

export function defaultCurrencyForCountry(countryCode: string): string {
  return countryByCode(countryCode).defaultCurrency;
}

export function vaultPreview(industry: Industry): string {
  const folders = VAULT_FOLDERS_BY_INDUSTRY[industry] ?? VAULT_FOLDERS_BY_INDUSTRY.Other;
  return folders.slice(0, 5).join(" · ");
}

export function SelectField({
  value,
  onChange,
  options,
  testId,
  className,
  size = "md",
  searchable,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  testId?: string;
  className?: string;
  size?: "sm" | "md";
  searchable?: boolean;
  children?: ReactNode;
}) {
  return (
    <Select
      value={value}
      onValueChange={onChange}
      options={options}
      data-testid={testId}
      className={className}
      size={size}
      searchable={searchable}
    />
  );
}
