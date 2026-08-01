import type { EmployeeMaster, VendorMaster, CustomerMaster } from "@/lib/v4RuleBookTypes";
import { employeeToApi, mapEmployee, mapVendor, vendorToApi, mapCustomer, customerToApi } from "@/lib/ruleBookConfigApi";

export type PendingVendorRecord = {
  id: number;
  detectedName: string;
  detectedAbn?: string;
  detectedAddress?: string;
  sourceInvoiceId?: number;
  confidence: number;
  status: string;
  promotedMasterId?: string;
  createdAt: string;
  resolvedAt?: string;
};

export type PendingCustomerRecord = PendingVendorRecord;

function mapPendingVendor(raw: Record<string, unknown>): PendingVendorRecord {
  return {
    id: Number(raw.id),
    detectedName: String(raw.detected_name),
    detectedAbn: raw.detected_abn as string | undefined,
    detectedAddress: raw.detected_address as string | undefined,
    sourceInvoiceId: raw.source_invoice_id as number | undefined,
    confidence: Number(raw.confidence ?? 0),
    status: String(raw.status),
    promotedMasterId: raw.promoted_master_id as string | undefined,
    createdAt: String(raw.created_at),
    resolvedAt: raw.resolved_at as string | undefined,
  };
}

function mapPendingCustomer(raw: Record<string, unknown>): PendingCustomerRecord {
  return mapPendingVendor(raw);
}

export function customerMasterFromApi(raw: Record<string, unknown>): CustomerMaster {
  const { db_id: _dbId, ...rest } = raw;
  return mapCustomer(rest);
}

export function customerMasterToCreateBody(customer: Partial<CustomerMaster>) {
  const api = customerToApi({
    id: customer.id ?? "",
    name: customer.name ?? "New customer",
    aliases: customer.aliases ?? [],
    abn: customer.abn ?? "",
    billingAddress: customer.billingAddress ?? {
      street: "",
      suburb: "",
      postcode: "",
      country: "",
    },
    defaultLedger: customer.defaultLedger ?? "",
    defaultSubLedger: customer.defaultSubLedger ?? "",
    paymentTerms: customer.paymentTerms ?? "",
    status: customer.status ?? "Pending registration",
    registeredOn: customer.registeredOn ?? "",
    totalRevenueYTD: customer.totalRevenueYTD ?? 0,
    invoiceCount: customer.invoiceCount ?? 0,
    matchConfidence: customer.matchConfidence ?? 0,
  });
  const { id, ...body } = api;
  return { ...body, master_id: id || undefined };
}

export function customerMasterToUpdateBody(patch: Partial<CustomerMaster>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (patch.name != null) out.name = patch.name;
  if (patch.aliases != null) out.aliases = patch.aliases;
  if (patch.abn != null) out.abn = patch.abn;
  if (patch.billingAddress != null) {
    out.billing_address = {
      street: patch.billingAddress.street,
      suburb: patch.billingAddress.suburb,
      postcode: patch.billingAddress.postcode,
      country: patch.billingAddress.country,
    };
  }
  if (patch.defaultLedger != null) out.default_ledger = patch.defaultLedger;
  if (patch.defaultSubLedger != null) out.default_sub_ledger = patch.defaultSubLedger;
  if (patch.paymentTerms != null) out.payment_terms = patch.paymentTerms;
  if (patch.status != null) out.status = patch.status;
  if (patch.registeredOn != null) out.registered_on = patch.registeredOn;
  if (patch.totalRevenueYTD != null) out.total_revenue_ytd = patch.totalRevenueYTD;
  if (patch.invoiceCount != null) out.invoice_count = patch.invoiceCount;
  if (patch.matchConfidence != null) out.match_confidence = patch.matchConfidence;
  return out;
}

export function vendorMasterFromApi(raw: Record<string, unknown>): VendorMaster {
  const { db_id: _dbId, ...rest } = raw;
  return mapVendor(rest);
}

export function employeeMasterFromApi(raw: Record<string, unknown>): EmployeeMaster {
  const { db_id: _dbId, ...rest } = raw;
  return mapEmployee(rest);
}

export function vendorMasterToCreateBody(vendor: Partial<VendorMaster>) {
  const api = vendorToApi({
    id: vendor.id ?? "",
    name: vendor.name ?? "New vendor",
    aliases: vendor.aliases ?? [],
    abn: vendor.abn ?? "",
    billingAddress: vendor.billingAddress ?? {
      street: "",
      suburb: "",
      postcode: "",
      country: "",
    },
    bank: vendor.bank ?? { accountNumber: "", accountName: "", bankName: "" },
    defaultLedger: vendor.defaultLedger ?? "",
    defaultSubLedger: vendor.defaultSubLedger ?? "",
    paymentTerms: vendor.paymentTerms ?? "",
    status: vendor.status ?? "Pending registration",
    registeredOn: vendor.registeredOn ?? "",
    totalSpendYTD: vendor.totalSpendYTD ?? 0,
    invoiceCount: vendor.invoiceCount ?? 0,
    matchConfidence: vendor.matchConfidence ?? 0,
  });
  const { id, ...body } = api;
  return { ...body, master_id: id || undefined };
}

export function vendorMasterToUpdateBody(patch: Partial<VendorMaster>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (patch.name != null) out.name = patch.name;
  if (patch.aliases != null) out.aliases = patch.aliases;
  if (patch.abn != null) out.abn = patch.abn;
  if (patch.billingAddress != null) {
    out.billing_address = {
      street: patch.billingAddress.street,
      suburb: patch.billingAddress.suburb,
      postcode: patch.billingAddress.postcode,
      country: patch.billingAddress.country,
    };
  }
  if (patch.bank != null) {
    out.bank = {
      ...(patch.bank.bsb != null ? { bsb: patch.bank.bsb } : {}),
      account_number: patch.bank.accountNumber,
      account_name: patch.bank.accountName,
      bank_name: patch.bank.bankName,
      ...(patch.bank.swift != null ? { swift: patch.bank.swift } : {}),
      ...(patch.bank.iban != null ? { iban: patch.bank.iban } : {}),
    };
  }
  if (patch.defaultLedger != null) out.default_ledger = patch.defaultLedger;
  if (patch.defaultSubLedger != null) out.default_sub_ledger = patch.defaultSubLedger;
  if (patch.paymentTerms != null) out.payment_terms = patch.paymentTerms;
  if (patch.status != null) out.status = patch.status;
  if (patch.registeredOn != null) out.registered_on = patch.registeredOn;
  if (patch.totalSpendYTD != null) out.total_spend_ytd = patch.totalSpendYTD;
  if (patch.invoiceCount != null) out.invoice_count = patch.invoiceCount;
  if (patch.matchConfidence != null) out.match_confidence = patch.matchConfidence;
  return out;
}

export function employeeMasterToCreateBody(employee: Partial<EmployeeMaster>) {
  const api = employeeToApi({
    id: employee.id ?? "",
    name: employee.name ?? "New employee",
    role: employee.role ?? "",
    email: employee.email ?? "",
    whatsappNumber: employee.whatsappNumber ?? "",
    whatsappNumber2: employee.whatsappNumber2 ?? "",
    viberNumber: employee.viberNumber,
    dateOfJoining: employee.dateOfJoining ?? "",
    department: employee.department ?? "",
    location: employee.location ?? "",
    division: employee.division ?? "",
    supervisor1: employee.supervisor1 ?? "",
    supervisor2: employee.supervisor2 ?? "",
    bank: employee.bank ?? { accountNumber: "", accountName: "", bankName: "" },
    budget: employee.budget ?? { monthly: 0, quarterly: 0, annual: 0, categories: [] },
    advanceParentLedger: employee.advanceParentLedger ?? "",
    advanceSubLedger: employee.advanceSubLedger ?? "",
    ytdSpent: employee.ytdSpent ?? 0,
    mtdSpent: employee.mtdSpent ?? 0,
    qtdSpent: employee.qtdSpent ?? 0,
    claimCount: employee.claimCount ?? 0,
    lastClaim: employee.lastClaim ?? "",
    status: employee.status ?? "Pending verification",
  });
  const { id, ...body } = api;
  return { ...body, master_id: id || undefined };
}

export function employeeMasterToUpdateBody(patch: Partial<EmployeeMaster>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (patch.name != null) out.name = patch.name;
  if (patch.role != null) out.role = patch.role;
  if (patch.email != null) out.email = patch.email;
  if (patch.whatsappNumber != null) out.whatsapp_number = patch.whatsappNumber;
  if (patch.whatsappNumber2 != null) out.whatsapp_number_2 = patch.whatsappNumber2;
  if (patch.viberNumber != null) out.viber_number = patch.viberNumber;
  if (patch.dateOfJoining != null) out.date_of_joining = patch.dateOfJoining;
  if (patch.department != null) out.department = patch.department;
  if (patch.location != null) out.location = patch.location;
  if (patch.division != null) out.division = patch.division;
  if (patch.supervisor1 != null) out.supervisor_1 = patch.supervisor1;
  if (patch.supervisor2 != null) out.supervisor_2 = patch.supervisor2;
  if (patch.bank != null) {
    out.bank = {
      ...(patch.bank.bsb != null ? { bsb: patch.bank.bsb } : {}),
      account_number: patch.bank.accountNumber,
      account_name: patch.bank.accountName,
      bank_name: patch.bank.bankName,
      ...(patch.bank.swift != null ? { swift: patch.bank.swift } : {}),
      ...(patch.bank.iban != null ? { iban: patch.bank.iban } : {}),
    };
  }
  if (patch.budget != null) out.budget = patch.budget;
  if (patch.advanceParentLedger != null) out.advance_parent_ledger = patch.advanceParentLedger;
  if (patch.ytdSpent != null) out.ytd_spent = patch.ytdSpent;
  if (patch.mtdSpent != null) out.mtd_spent = patch.mtdSpent;
  if (patch.qtdSpent != null) out.qtd_spent = patch.qtdSpent;
  if (patch.claimCount != null) out.claim_count = patch.claimCount;
  if (patch.lastClaim != null) out.last_claim = patch.lastClaim;
  if (patch.status != null) out.status = patch.status;
  return out;
}

export { mapPendingCustomer, mapPendingVendor };
