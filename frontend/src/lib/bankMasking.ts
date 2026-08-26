/** True when a value is a masked display echo, not a real account identifier. */
export function looksMaskedBankValue(value?: string | null): boolean {
  const token = (value || "").trim();
  if (!token) return false;
  if (/[•*]/.test(token)) return true;
  return token.startsWith("****");
}

export function bankUpdatePayload(bank: {
  bsb?: string;
  accountNumber: string;
  accountName: string;
  bankName: string;
  swift?: string;
  iban?: string;
}): Record<string, unknown> {
  const out: Record<string, unknown> = {
    account_name: bank.accountName,
    bank_name: bank.bankName,
  };
  if (bank.bsb != null && !looksMaskedBankValue(bank.bsb)) {
    out.bsb = bank.bsb;
  }
  if (!looksMaskedBankValue(bank.accountNumber)) {
    out.account_number = bank.accountNumber;
  }
  if (bank.swift != null) {
    out.swift = bank.swift;
  }
  if (bank.iban != null && !looksMaskedBankValue(bank.iban)) {
    out.iban = bank.iban;
  }
  return out;
}
