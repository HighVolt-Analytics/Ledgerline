import { Layers, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { DocumentSetRule } from "@/lib/v4RuleBookTypes";

type DocumentSetsPanelProps = {
  sets: DocumentSetRule[];
  onChange: (sets: DocumentSetRule[]) => void;
};

export function DocumentSetsPanel({ sets, onChange }: DocumentSetsPanelProps) {
  const addSet = () => {
    const id = `ds-${Date.now()}`;
    onChange([
      ...sets,
      {
        id,
        pattern: "",
        setName: "New document set",
        isolated: false,
      },
    ]);
  };

  const updateSet = (id: string, patch: Partial<DocumentSetRule>) => {
    onChange(sets.map((set) => (set.id === id ? { ...set, ...patch } : set)));
  };

  const removeSet = (id: string) => {
    onChange(sets.filter((set) => set.id !== id));
  };

  return (
    <Card className="p-4" data-testid="document-sets-panel">
      <div className="flex items-start justify-between gap-3 mb-1">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" />
            Document sets
          </h3>
          <p className="text-xs text-muted-foreground mt-1">
            Group vault documents by PO or invoice number pattern. Used on the Vault → Document sets
            tab.
          </p>
        </div>
        <Button type="button" size="sm" variant="outline" className="h-8 text-xs" onClick={addSet}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add set
        </Button>
      </div>

      <div className="mt-4 space-y-3">
        {sets.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6 border border-dashed rounded-md">
            No document sets defined.
          </p>
        ) : (
          sets.map((set) => (
            <div
              key={set.id}
              className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end border border-border rounded-md p-3"
              data-testid={`document-set-${set.id}`}
            >
              <div className="space-y-1.5">
                <label
                  htmlFor={`set-name-${set.id}`}
                  className="text-xs text-muted-foreground"
                >
                  Set name
                </label>
                <Input
                  id={`set-name-${set.id}`}
                  value={set.setName}
                  onChange={(e) => updateSet(set.id, { setName: e.target.value })}
                  className="h-9 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label
                  htmlFor={`set-pattern-${set.id}`}
                  className="text-xs text-muted-foreground"
                >
                  Match pattern
                </label>
                <Input
                  id={`set-pattern-${set.id}`}
                  value={set.pattern}
                  onChange={(e) => updateSet(set.id, { pattern: e.target.value })}
                  className="h-9 text-sm font-mono"
                  placeholder="PO-MKT-2026-014"
                />
              </div>
              <div className="flex items-center gap-2 pb-1">
                <Switch
                  id={`set-isolated-${set.id}`}
                  checked={set.isolated ?? false}
                  onCheckedChange={(isolated) => updateSet(set.id, { isolated })}
                />
                <label htmlFor={`set-isolated-${set.id}`} className="text-xs text-muted-foreground">
                  Isolated
                </label>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-9 px-2 text-destructive hover:text-destructive"
                onClick={() => removeSet(set.id)}
                aria-label={`Delete ${set.setName}`}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))
        )}
      </div>

      {sets.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {sets.map((set) => (
            <Badge key={set.id} variant="outline" className="text-[10px] font-normal">
              {set.setName || "Untitled"} · {set.pattern || "no pattern"}
            </Badge>
          ))}
        </div>
      )}
    </Card>
  );
}
