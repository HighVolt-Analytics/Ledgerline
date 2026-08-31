import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import type { IntegrationBrandId } from "@/components/integrations/types";

type BillProcessingConnectionChipProps = {
  brandId?: IntegrationBrandId;
  providerName: string;
  organisationName?: string | null;
};

export function BillProcessingConnectionChip({
  brandId,
  providerName,
  organisationName,
}: BillProcessingConnectionChipProps) {
  const org = organisationName?.trim() || "";
  const name = org || providerName;

  return (
    <div
      className="inline-flex min-h-7 items-center gap-2"
      data-testid="bill-processing-connection-chip"
    >
      {brandId ? <IntegrationBrandIcon id={brandId} size={16} /> : null}
      <span className="text-sm font-medium text-foreground">{name}</span>
      {org && org !== providerName ? (
        <span className="text-xs text-muted-foreground">{providerName}</span>
      ) : null}
      <span
        className="rounded-full border border-emerald-500 px-2 py-0.5 text-[11px] font-medium leading-none text-emerald-600"
        data-testid="bill-processing-connected-badge"
      >
        Connected
      </span>
    </div>
  );
}
