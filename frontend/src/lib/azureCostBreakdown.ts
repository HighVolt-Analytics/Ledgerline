import type { CreditLedgerEntry } from "@/api/types";

export type AzureCostLineItem = {
  service: string;
  model: string;
  operation: string;
  cost_usd: number;
  rate_description: string;
  pages?: number;
  input_tokens?: number;
  output_tokens?: number;
};

export type AzureCostBreakdownView = {
  provider: string;
  pages: number;
  totalUsd: number;
  lineItems: AzureCostLineItem[];
  rates?: Record<string, number>;
  inputTokensTotal?: number;
  outputTokensTotal?: number;
};

function num(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return undefined;
}

function legacyLineItems(raw: Record<string, unknown>): AzureCostLineItem[] {
  const provider = String(raw.provider ?? "azure_di");
  const pages = num(raw.pages) ?? 0;
  const items: AzureCostLineItem[] = [];

  if (provider === "azure_foundry_vision") {
    const inputTokens = num(raw.foundry_input_tokens) ?? 0;
    const outputTokens = num(raw.foundry_output_tokens) ?? 0;
    const inputUsd = num(raw.foundry_input_usd) ?? 0;
    const outputUsd = num(raw.foundry_output_usd) ?? 0;
    const calls = num(raw.vision_calls) ?? 3;
    items.push({
      service: "Azure AI Foundry",
      model: "gpt-4o (vision)",
      operation: `vision_pipeline (${calls} calls)`,
      pages,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      rate_description: "Input + output token pricing (see rates below)",
      cost_usd: inputUsd + outputUsd,
    });
    return items;
  }

  const layoutUsd = num(raw.di_layout_usd) ?? 0;
  const invoiceUsd = num(raw.di_invoice_usd) ?? 0;
  const layoutPages = num(raw.di_layout_pages) ?? pages;
  const invoicePages = num(raw.di_invoice_pages) ?? pages;
  const inputTokens = num(raw.openai_mini_input_tokens) ?? 0;
  const outputTokens = num(raw.openai_mini_output_tokens) ?? 0;
  const inputUsd = num(raw.openai_mini_input_usd) ?? 0;
  const outputUsd = num(raw.openai_mini_output_usd) ?? 0;

  if (layoutUsd > 0) {
    items.push({
      service: "Azure Document Intelligence",
      model: "prebuilt-layout",
      operation: "layout_analysis",
      pages: layoutPages,
      rate_description: "Per-page prebuilt layout pricing",
      cost_usd: layoutUsd,
    });
  }
  if (invoiceUsd > 0) {
    items.push({
      service: "Azure Document Intelligence",
      model: "prebuilt-invoice",
      operation: "invoice_extraction",
      pages: invoicePages,
      rate_description: "Per-page prebuilt invoice pricing",
      cost_usd: invoiceUsd,
    });
  }
  if (inputUsd + outputUsd > 0) {
    items.push({
      service: "Azure OpenAI",
      model: "gpt-4o-mini",
      operation: "classify + extract",
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      rate_description: "Input + output token pricing (see rates below)",
      cost_usd: inputUsd + outputUsd,
    });
  }
  return items;
}

export function parseAzureCostBreakdown(
  raw: Record<string, unknown> | null | undefined,
  fallbackTotalUsd = 0
): AzureCostBreakdownView | null {
  if (!raw || typeof raw !== "object") return null;

  const lineItemsRaw = raw.line_items;
  const lineItems =
    Array.isArray(lineItemsRaw) && lineItemsRaw.length > 0
      ? lineItemsRaw
          .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
          .map((item) => ({
            service: String(item.service ?? "Azure"),
            model: String(item.model ?? "—"),
            operation: String(item.operation ?? "—"),
            cost_usd: num(item.cost_usd) ?? 0,
            rate_description: String(item.rate_description ?? ""),
            pages: num(item.pages),
            input_tokens: num(item.input_tokens),
            output_tokens: num(item.output_tokens),
          }))
      : legacyLineItems(raw);

  if (lineItems.length === 0 && fallbackTotalUsd <= 0) return null;

  const totalUsd =
    num(raw.total_usd) ??
    fallbackTotalUsd ??
    lineItems.reduce((sum, item) => sum + item.cost_usd, 0);

  const inputTokensTotal = lineItems.reduce(
    (sum, item) => sum + (item.input_tokens ?? 0),
    0
  );
  const outputTokensTotal = lineItems.reduce(
    (sum, item) => sum + (item.output_tokens ?? 0),
    0
  );

  const ratesRaw = raw.rates;
  const rates: Record<string, number> | undefined =
    ratesRaw && typeof ratesRaw === "object"
      ? (Object.fromEntries(
          Object.entries(ratesRaw as Record<string, unknown>).filter(
            (entry): entry is [string, number] => typeof entry[1] === "number"
          )
        ) as Record<string, number>)
      : undefined;

  return {
    provider: String(raw.provider ?? "azure_di"),
    pages: num(raw.pages) ?? 0,
    totalUsd,
    lineItems,
    rates,
    inputTokensTotal: inputTokensTotal > 0 ? inputTokensTotal : undefined,
    outputTokensTotal: outputTokensTotal > 0 ? outputTokensTotal : undefined,
  };
}

export function formatProviderLabel(provider: string): string {
  if (provider === "azure_foundry_vision") return "Azure AI Foundry (vision)";
  if (provider === "azure_di") return "Azure DI + OpenAI";
  if (provider === "gemini_vision") return "Gemini Vision";
  return provider.replace(/_/g, " ");
}

export function formatOperationLabel(operation: string): string {
  return operation.replace(/_/g, " ");
}

export function ledgerAzureEntries(items: CreditLedgerEntry[]): CreditLedgerEntry[] {
  return items.filter(
    (row) =>
      row.azure_cost_usd != null &&
      row.azure_cost_usd > 0 &&
      row.event_type === "upload_charge"
  );
}

export function sumAzureCostUsd(items: CreditLedgerEntry[]): number {
  return items.reduce((sum, row) => sum + (row.azure_cost_usd ?? 0), 0);
}
