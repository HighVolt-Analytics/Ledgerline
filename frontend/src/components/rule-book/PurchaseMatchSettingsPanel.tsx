import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";

type PurchaseMatchConfig = NonNullable<RuleBookConfigState["purchaseMatch"]>;

type PurchaseMatchSettingsPanelProps = {
  value: PurchaseMatchConfig | undefined;
  onChange: (next: PurchaseMatchConfig | undefined) => void;
};

export function defaultPurchaseMatchConfig(): PurchaseMatchConfig {
  return {
    baseUom: "EA",
    qtyTolerancePct: 0,
    uomConversions: [],
  };
}

export function PurchaseMatchSettingsPanel({
  value,
  onChange,
}: PurchaseMatchSettingsPanelProps) {
  const cfg = value ?? defaultPurchaseMatchConfig();

  const patch = (partial: Partial<PurchaseMatchConfig>) => {
    onChange({ ...cfg, ...partial });
  };

  const addConversion = () => {
    patch({
      uomConversions: [
        ...cfg.uomConversions,
        {
          id: `uom-${Date.now()}`,
          fromUom: "CTN",
          toUom: cfg.baseUom,
          factor: 12,
        },
      ],
    });
  };

  const updateConversion = (
    index: number,
    partial: Partial<PurchaseMatchConfig["uomConversions"][number]>
  ) => {
    const next = cfg.uomConversions.map((row, i) =>
      i === index ? { ...row, ...partial } : row
    );
    patch({ uomConversions: next });
  };

  const removeConversion = (index: number) => {
    patch({ uomConversions: cfg.uomConversions.filter((_, i) => i !== index) });
  };

  return (
    <Card className="p-4" data-testid="purchase-match-settings-panel">
      <h3 className="text-sm font-semibold mb-1">Three-way match — UOM</h3>
      <p className="text-xs text-muted-foreground mb-4">
        Normalize PO, invoice, and GRN quantities to a base unit before comparing. GRN may use a
        different operational currency without affecting FX booking.
      </p>
      <div className="grid gap-4 sm:grid-cols-2 mb-4">
        <div className="space-y-1.5">
          <label htmlFor="pm-base-uom" className="text-xs text-muted-foreground">
            Base UOM
          </label>
          <Input
            id="pm-base-uom"
            value={cfg.baseUom}
            onChange={(e) => patch({ baseUom: e.target.value.toUpperCase() })}
            className="h-9 font-mono text-sm uppercase"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="pm-qty-tolerance" className="text-xs text-muted-foreground">
            Qty tolerance (%)
          </label>
          <Input
            id="pm-qty-tolerance"
            type="number"
            min={0}
            step={0.1}
            value={cfg.qtyTolerancePct}
            onChange={(e) => patch({ qtyTolerancePct: Number(e.target.value) || 0 })}
            className="h-9 text-sm"
          />
        </div>
      </div>

      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-medium text-muted-foreground">UOM conversion rules</p>
        <Button type="button" variant="outline" size="sm" onClick={addConversion}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add rule
        </Button>
      </div>

      {cfg.uomConversions.length === 0 ? (
        <p className="text-xs text-muted-foreground rounded-md border border-dashed p-3">
          No conversions — quantities compared in document UOM only.
        </p>
      ) : (
        <div className="space-y-2">
          {cfg.uomConversions.map((row, index) => (
            <div
              key={row.id}
              className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_1fr_auto] items-end rounded-md border p-2"
            >
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground">Vendor key</span>
                <Input
                  value={row.vendorKey ?? ""}
                  onChange={(e) => updateConversion(index, { vendorKey: e.target.value })}
                  placeholder="sysco-foods"
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground">From UOM</span>
                <Input
                  value={row.fromUom}
                  onChange={(e) =>
                    updateConversion(index, { fromUom: e.target.value.toUpperCase() })
                  }
                  className="h-8 font-mono text-xs uppercase"
                />
              </div>
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground">Factor → {cfg.baseUom}</span>
                <Input
                  type="number"
                  min={0}
                  step={1}
                  value={row.factor}
                  onChange={(e) =>
                    updateConversion(index, { factor: Number(e.target.value) || 1 })
                  }
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-1">
                <span className="text-[10px] text-muted-foreground">SKU (optional)</span>
                <Input
                  value={row.sku ?? ""}
                  onChange={(e) => updateConversion(index, { sku: e.target.value })}
                  className="h-8 text-xs"
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => removeConversion(index)}
                aria-label="Remove conversion"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
