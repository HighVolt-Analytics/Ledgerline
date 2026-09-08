import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { BillProcessingConnectionChip } from "@/components/settings/tax/BillProcessingConnectionChip";
import { NoBillProcessingTaxNote } from "@/components/settings/tax/NoBillProcessingTaxNote";
import { XeroTaxRatesView } from "@/components/settings/tax/XeroTaxRatesView";
import { useTaxRates } from "@/hooks/useTaxRates";
import {
  billProcessingBrandId,
  billProcessingTaxAdapter,
  resolveBillProcessingTaxSource,
} from "@/lib/billProcessingTax";

type TaxRatesPanelProps = {
  canEdit?: boolean;
};

export function TaxRatesPanel({ canEdit = false }: TaxRatesPanelProps) {
  const { data, isLoading, isError, blocked } = useTaxRates();
  const source = resolveBillProcessingTaxSource(data);

  if (isLoading || blocked) {
    return (
      <Card className="w-full overflow-hidden" data-testid="tax-rates-panel">
        <InlineTableSkeleton rows={6} columns={4} />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="w-full p-6 text-sm text-destructive" data-testid="tax-rates-panel">
        Could not load tax rates for this organisation.
      </Card>
    );
  }

  if (source.kind === "none") {
    return (
      <div className="w-full space-y-4" data-testid="tax-rates-panel">
        <h2 className="text-sm font-semibold">Tax rates</h2>
        <NoBillProcessingTaxNote />
      </div>
    );
  }

  if (source.kind === "unsupported") {
    return (
      <div className="w-full space-y-4" data-testid="tax-rates-panel">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold">Tax rates</h2>
          <BillProcessingConnectionChip
            brandId={billProcessingBrandId(source.providerId)}
            providerName={source.providerName}
          />
        </div>
        <Card className="p-8">
          <p className="text-center text-sm text-muted-foreground">
            {source.providerName} tax rates are not shown in Settings yet. This section will
            switch to that platform's tax configuration when it is added.
          </p>
        </Card>
      </div>
    );
  }

  if (source.adapterId === "xero" || source.adapterId === "qbo") {
    return (
      <div data-testid="tax-rates-panel">
        <XeroTaxRatesView
          adapterId={source.adapterId}
          canEdit={canEdit}
          payload={data ?? { tax_rates: [] }}
        />
      </div>
    );
  }

  const adapter = billProcessingTaxAdapter(source.adapterId);
  return (
    <div className="w-full space-y-4" data-testid="tax-rates-panel">
      <h2 className="text-sm font-semibold">Tax rates</h2>
      <Card className="p-8">
        <p className="text-center text-sm text-muted-foreground">
          {adapter.name} tax rates are not shown in Settings yet.
        </p>
      </Card>
    </div>
  );
}
