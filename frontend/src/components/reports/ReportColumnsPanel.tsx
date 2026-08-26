import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { ReportColumnLayoutItem } from "@/api/types";
import { useReportLayoutMutations } from "@/hooks/useReportCatalog";
import { useToast } from "@/context/ToastContext";
import { insertKeyInCatalogOrder, moveVisibleKey } from "@/lib/reportColumnLayout";

const CATALOG_DEFAULT = "";

type ReportColumnsPanelProps = {
  reportId: string;
  catalogColumns: string[];
  layouts: ReportColumnLayoutItem[];
  visibleKeys: string[];
  selectedLayoutId: string;
  onVisibleKeysChange: (keys: string[]) => void;
  onSelectedLayoutIdChange: (id: string) => void;
};

export function ReportColumnsPanel({
  reportId,
  catalogColumns,
  layouts,
  visibleKeys,
  selectedLayoutId,
  onVisibleKeysChange,
  onSelectedLayoutIdChange,
}: ReportColumnsPanelProps) {
  const { toast } = useToast();
  const mutations = useReportLayoutMutations(reportId);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const selected = layouts.find((row) => String(row.id) === selectedLayoutId);

  const options = useMemo(
    () => [
      { value: CATALOG_DEFAULT, label: "Catalog default" },
      ...layouts.map((row) => ({
        value: String(row.id),
        label: row.is_default ? `${row.name} (default)` : row.name,
      })),
    ],
    [layouts]
  );

  useEffect(() => {
    if (selectedLayoutId && !layouts.some((row) => String(row.id) === selectedLayoutId)) {
      onSelectedLayoutIdChange(CATALOG_DEFAULT);
      onVisibleKeysChange(catalogColumns);
    }
  }, [catalogColumns, layouts, onSelectedLayoutIdChange, onVisibleKeysChange, selectedLayoutId]);

  function applyLayout(id: string) {
    onSelectedLayoutIdChange(id);
    if (!id) {
      onVisibleKeysChange(catalogColumns);
      return;
    }
    const layout = layouts.find((row) => String(row.id) === id);
    if (layout) {
      onVisibleKeysChange(layout.column_config.columns);
    }
  }

  async function saveNew() {
    const trimmed = name.trim();
    if (!trimmed || visibleKeys.length === 0 || mutations.create.isPending) return;
    try {
      const created = await mutations.create.mutateAsync({
        name: trimmed,
        column_config: { columns: visibleKeys },
      });
      setName("");
      onSelectedLayoutIdChange(String(created.id));
      toast({ title: "Layout saved" });
    } catch (err) {
      toast({
        title: "Could not save layout",
        description: err instanceof Error ? err.message : "Try again later.",
        variant: "destructive",
      });
    }
  }

  async function markDefault() {
    if (!selected) return;
    try {
      await mutations.setDefault.mutateAsync(selected.id);
      toast({ title: `${selected.name} is now the default` });
    } catch (err) {
      toast({
        title: "Could not set default",
        description: err instanceof Error ? err.message : "Try again later.",
        variant: "destructive",
      });
    }
  }

  async function removeSelected() {
    if (!selected) return;
    try {
      await mutations.remove.mutateAsync(selected.id);
      onSelectedLayoutIdChange(CATALOG_DEFAULT);
      onVisibleKeysChange(catalogColumns);
      toast({ title: "Layout deleted" });
    } catch (err) {
      toast({
        title: "Could not delete layout",
        description: err instanceof Error ? err.message : "Try again later.",
        variant: "destructive",
      });
    }
  }

  return (
    <div className="space-y-3">
      <Button
        type="button"
        variant={open ? "default" : "outline"}
        className="min-h-11"
        data-testid={`button-columns-${reportId}`}
        onClick={() => setOpen((value) => !value)}
      >
        Columns
      </Button>
      {open ? (
        <Card className="p-4 space-y-3" data-testid={`columns-panel-${reportId}`}>
          <Select
            value={selectedLayoutId}
            onValueChange={applyLayout}
            options={options}
            data-testid={`select-layout-${reportId}`}
            size="md"
          />
          <ul className="space-y-2">
            {catalogColumns.map((column) => {
              const visibleIndex = visibleKeys.indexOf(column);
              const checked = visibleIndex >= 0;
              return (
                <li
                  key={column}
                  className="flex items-center gap-2 min-h-11"
                  data-testid={`column-row-${reportId}-${column}`}
                >
                  <Switch
                    checked={checked}
                    onCheckedChange={(on) => {
                      if (on) {
                        onVisibleKeysChange(
                          insertKeyInCatalogOrder(visibleKeys, column, catalogColumns)
                        );
                        return;
                      }
                      if (visibleKeys.length <= 1) return;
                      onVisibleKeysChange(visibleKeys.filter((key) => key !== column));
                    }}
                    aria-label={`Show ${column}`}
                    data-testid={`column-toggle-${reportId}-${column}`}
                  />
                  <span className="flex-1 text-sm">{column}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="min-h-11 min-w-11"
                    disabled={!checked || visibleIndex <= 0}
                    aria-label={`Move ${column} up`}
                    data-testid={`column-up-${reportId}-${column}`}
                    onClick={() =>
                      onVisibleKeysChange(moveVisibleKey(visibleKeys, visibleIndex, -1))
                    }
                  >
                    <ChevronUp />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="min-h-11 min-w-11"
                    disabled={!checked || visibleIndex < 0 || visibleIndex >= visibleKeys.length - 1}
                    aria-label={`Move ${column} down`}
                    data-testid={`column-down-${reportId}-${column}`}
                    onClick={() =>
                      onVisibleKeysChange(moveVisibleKey(visibleKeys, visibleIndex, 1))
                    }
                  >
                    <ChevronDown />
                  </Button>
                </li>
              );
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Layout name"
              aria-label="Layout name"
              className="h-11 w-[14rem]"
              data-testid={`input-layout-name-${reportId}`}
            />
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={!name.trim() || visibleKeys.length === 0 || mutations.create.isPending}
              data-testid={`button-save-layout-${reportId}`}
              onClick={() => void saveNew()}
            >
              Save as new layout
            </Button>
          </div>
          {selected ? (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                disabled={selected.is_default || mutations.setDefault.isPending}
                data-testid={`button-default-layout-${reportId}`}
                onClick={() => void markDefault()}
              >
                Set as default
              </Button>
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                disabled={mutations.remove.isPending}
                data-testid={`button-delete-layout-${reportId}`}
                onClick={() => void removeSelected()}
              >
                Delete
              </Button>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
