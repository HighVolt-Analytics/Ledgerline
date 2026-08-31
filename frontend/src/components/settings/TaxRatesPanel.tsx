import { createPortal } from "react-dom";
import { Loader2, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import type { OrgTaxRateRow, OrgTaxRateWrite } from "@/api/types";
import { TaxRateFormDialog } from "@/components/settings/TaxRateFormDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { useToast } from "@/context/ToastContext";
import {
  useCreateTaxRate,
  useDeleteTaxRate,
  useSyncTaxRates,
  useTaxRates,
  useUpdateTaxRate,
} from "@/hooks/useTaxRates";
import { formatTaxPercent, taxRateTypeLabel } from "@/lib/taxRates";

type TaxRatesPanelProps = {
  canEdit?: boolean;
};

function rateKey(row: OrgTaxRateRow): string {
  return row.xero_tax_type || row.id;
}

export function TaxRatesPanel({ canEdit = false }: TaxRatesPanelProps) {
  const { toast } = useToast();
  const { data, isLoading, isError, blocked } = useTaxRates();
  const createMutation = useCreateTaxRate();
  const updateMutation = useUpdateTaxRate();
  const deleteMutation = useDeleteTaxRate();
  const syncMutation = useSyncTaxRates();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<OrgTaxRateRow | null>(null);
  const [pendingDelete, setPendingDelete] = useState<OrgTaxRateRow | null>(null);
  const rows = data?.tax_rates ?? [];
  const xeroConnected = Boolean(data?.xero_connected);
  const formBusy = createMutation.isPending || updateMutation.isPending;
  const colCount = canEdit ? 5 : 3;

  const closeForm = () => {
    setDialogOpen(false);
    setEditing(null);
  };

  const handleSave = async (row: OrgTaxRateWrite) => {
    try {
      if (editing) {
        await updateMutation.mutateAsync({ rateId: rateKey(editing), body: row });
        toast({ title: xeroConnected ? "Tax rate updated in Xero" : "Tax rate updated" });
      } else {
        await createMutation.mutateAsync(row);
        toast({ title: xeroConnected ? "Tax rate saved in Xero" : "Tax rate saved" });
      }
      closeForm();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save tax rate";
      toast({ title: message, variant: "destructive" });
    }
  };

  const handleSync = async () => {
    try {
      const result = await syncMutation.mutateAsync();
      toast({
        title: `Synced ${result.tax_rates.length} tax rate${
          result.tax_rates.length === 1 ? "" : "s"
        } from Xero`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not sync tax rates from Xero";
      toast({ title: message, variant: "destructive" });
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await deleteMutation.mutateAsync(rateKey(pendingDelete));
      toast({
        title: xeroConnected ? "Tax rate deleted in Xero" : "Tax rate removed",
      });
      setPendingDelete(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not delete tax rate";
      toast({ title: message, variant: "destructive" });
    }
  };

  const lockedMessage = "This is a default Xero tax rate and cannot be changed.";

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

  return (
    <div className="w-full space-y-4" data-testid="tax-rates-panel">
      <div>
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-semibold">Tax rates</h2>
          {canEdit ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 cursor-pointer text-muted-foreground"
              onClick={() => void handleSync()}
              disabled={syncMutation.isPending}
              aria-label="Sync tax rates from Xero"
              title="Sync from Xero"
              data-testid="button-sync-tax-rates"
            >
              <RefreshCw className={syncMutation.isPending ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            </Button>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {xeroConnected
            ? "These rates match your connected Xero organisation. New and edited custom rates are written to Xero. Default Xero rates cannot be edited or deleted."
            : "Named rates for this organisation. Connect Xero in Integrations, then use sync to pull the live list."}
        </p>
      </div>

      <Card className="overflow-hidden rounded-xl">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Display name</th>
              {canEdit ? <th className="px-3 py-2 w-12 font-medium">Edit</th> : null}
              <th className="px-3 py-2 font-medium">Tax type</th>
              <th className="px-3 py-2 font-medium">Rate</th>
              {canEdit ? <th className="px-3 py-2 w-12 text-right font-medium"> </th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="px-3 py-8 text-center text-sm text-muted-foreground">
                  {xeroConnected
                    ? "No tax rates synced yet. Use the sync arrow to pull rates from Xero."
                    : "No tax rates yet. Add a rate, or connect Xero and sync."}
                </td>
              </tr>
            ) : (
              rows.map((row) => {
                const canDelete = row.can_delete !== false;
                const canMutate = row.can_edit !== false;
                return (
                  <tr key={row.id} className="row-band border-b border-border/60">
                    <td className="px-3 py-2">
                      <div>
                        <p>{row.display_name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {row.components
                            .map((component) => `${component.name} ${component.rate}%`)
                            .join(" · ")}
                        </p>
                      </div>
                    </td>
                    {canEdit ? (
                      <td className="px-3 py-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 cursor-pointer text-muted-foreground hover:text-foreground"
                          onClick={() => {
                            if (!canMutate) {
                              toast({ title: lockedMessage });
                              return;
                            }
                            setEditing(row);
                            setDialogOpen(true);
                          }}
                          aria-label={
                            canMutate
                              ? `Edit ${row.display_name}`
                              : `${row.display_name} cannot be edited`
                          }
                          title={canMutate ? "Edit tax rate" : lockedMessage}
                          data-testid={`button-edit-tax-rate-${row.id}`}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </td>
                    ) : null}
                    <td className="px-3 py-2">
                      <Badge variant="outline" className="text-[10px]">
                        {taxRateTypeLabel(row.tax_type)}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 tnum">{formatTaxPercent(row.total_rate)}</td>
                    {canEdit ? (
                      <td className="px-3 py-2 text-right">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 cursor-pointer text-muted-foreground hover:text-destructive"
                          onClick={() => {
                            if (!canDelete) {
                              toast({ title: lockedMessage });
                              return;
                            }
                            setPendingDelete(row);
                          }}
                          aria-label={
                            canDelete
                              ? `Delete ${row.display_name}`
                              : `${row.display_name} cannot be deleted`
                          }
                          title={canDelete ? "Delete tax rate" : lockedMessage}
                          data-testid={`button-delete-tax-rate-${row.id}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </Card>

      {canEdit ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="cursor-pointer"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
          data-testid="button-add-tax-rate"
        >
          <Plus className="mr-1 h-4 w-4" />
          Add tax rate
        </Button>
      ) : (
        <p className="text-sm text-muted-foreground">Only admins can edit tax rates.</p>
      )}

      <TaxRateFormDialog
        open={dialogOpen}
        busy={formBusy}
        editing={editing}
        existingNames={rows.map((row) => row.display_name)}
        onClose={closeForm}
        onSave={(row) => void handleSave(row)}
      />

      <ConfirmDialog
        open={pendingDelete != null}
        title="Delete tax rate?"
        description={
          xeroConnected
            ? `“${pendingDelete?.display_name ?? ""}” will be deleted in Xero as well as here.`
            : `Remove “${pendingDelete?.display_name ?? ""}” from this organisation?`
        }
        confirmLabel="Delete"
        destructive
        busy={deleteMutation.isPending}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
        data-testid="confirm-delete-tax-rate"
      />

      {syncMutation.isPending
        ? createPortal(
            <div
              className="fixed inset-0 z-[220] flex items-center justify-center bg-background/45 backdrop-blur-[1px]"
              data-testid="tax-rates-sync-overlay"
              role="status"
              aria-live="polite"
              aria-label="Syncing tax rates from Xero"
            >
              <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card/90 px-8 py-6 shadow-lg">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                <p className="text-sm text-muted-foreground">Syncing tax rates from Xero…</p>
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
