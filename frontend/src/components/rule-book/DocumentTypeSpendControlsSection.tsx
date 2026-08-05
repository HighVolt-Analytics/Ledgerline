import { Switch } from "@/components/ui/switch";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

type SpendControlsEditorProps = {
  draft: DocumentTypeDefinition;
  onChange: (patch: Pick<DocumentTypeDefinition, "budgetControl" | "advanceControl">) => void;
  disabled?: boolean;
};

/** Per-DT toggles: check employee budget / advance availability. */
export function DocumentTypeSpendControlsEditor({
  draft,
  onChange,
  disabled,
}: SpendControlsEditorProps) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        When on, validation checks whether the employee still has budget or advance left for
        this document. When off, those employee-level checks are skipped for this type.
      </p>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">Budget control</p>
          <p className="text-xs text-muted-foreground">
            Employee-level spending limits (period + category + department).
          </p>
        </div>
        <Switch
          checked={draft.budgetControl === true}
          disabled={disabled}
          onCheckedChange={(budgetControl) =>
            onChange({
              budgetControl,
              advanceControl: draft.advanceControl === true,
            })
          }
          aria-label="Budget control"
        />
      </div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">Advance control</p>
          <p className="text-xs text-muted-foreground">
            Employee-level advance float available (against-advance balance).
          </p>
        </div>
        <Switch
          checked={draft.advanceControl === true}
          disabled={disabled}
          onCheckedChange={(advanceControl) =>
            onChange({
              budgetControl: draft.budgetControl === true,
              advanceControl,
            })
          }
          aria-label="Advance control"
        />
      </div>
    </div>
  );
}

export function DocumentTypeSpendControlsDetail({
  docType,
}: {
  docType: DocumentTypeDefinition;
}) {
  return (
    <dl className="grid gap-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <dt className="text-muted-foreground">Budget control</dt>
        <dd className="font-medium">{docType.budgetControl === true ? "On" : "Off"}</dd>
      </div>
      <div className="flex items-center justify-between gap-2">
        <dt className="text-muted-foreground">Advance control</dt>
        <dd className="font-medium">{docType.advanceControl === true ? "On" : "Off"}</dd>
      </div>
    </dl>
  );
}
