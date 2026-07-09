/** v3 onboarding data — shared by /setup and settings. */

import type { ReactNode } from "react";
import { Select } from "@/components/ui/select";

export type CountryOption = {
  code: string;
  name: string;
  currency: string;
  symbol: string;
  locale: string;
  taxRate: number;
  taxLabel: string;
  dialCode: string;
};

export const COUNTRIES: CountryOption[] = [
  { code: "AU", name: "Australia", currency: "AUD", symbol: "A$", locale: "en-AU", taxRate: 10, taxLabel: "GST", dialCode: "+61" },
  { code: "US", name: "United States", currency: "USD", symbol: "$", locale: "en-US", taxRate: 8.5, taxLabel: "Sales Tax", dialCode: "+1" },
  { code: "GB", name: "United Kingdom", currency: "GBP", symbol: "£", locale: "en-GB", taxRate: 20, taxLabel: "VAT", dialCode: "+44" },
  { code: "IN", name: "India", currency: "INR", symbol: "₹", locale: "en-IN", taxRate: 18, taxLabel: "GST", dialCode: "+91" },
  { code: "SG", name: "Singapore", currency: "SGD", symbol: "S$", locale: "en-SG", taxRate: 9, taxLabel: "GST", dialCode: "+65" },
  { code: "NZ", name: "New Zealand", currency: "NZD", symbol: "NZ$", locale: "en-NZ", taxRate: 15, taxLabel: "GST", dialCode: "+64" },
  { code: "AE", name: "United Arab Emirates", currency: "AED", symbol: "د.إ", locale: "ar-AE", taxRate: 5, taxLabel: "VAT", dialCode: "+971" },
  { code: "DE", name: "Germany", currency: "EUR", symbol: "€", locale: "de-DE", taxRate: 19, taxLabel: "VAT", dialCode: "+49" },
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
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  testId?: string;
  className?: string;
  size?: "sm" | "md";
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
    />
  );
}
