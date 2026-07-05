import { Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import type { AiClassificationConfig } from "@/lib/v4RuleBookTypes";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

type AiClassificationSettingsPanelProps = {
  value: AiClassificationConfig;
  onChange: (next: AiClassificationConfig) => void;
  canEdit?: boolean;
};

const PROVIDERS = [
  {
    id: "azure_di" as const,
    title: "Azure Document Intelligence",
    description: "Layout OCR plus Azure OpenAI classify and extract",
    statusKey: "azure_di" as const,
  },
  {
    id: "azure_foundry_vision" as const,
    title: "Azure AI Foundry (GPT-4o Vision)",
    description: "GPT-4o reads PDF pages directly for OCR, classify, and extract",
    statusKey: "azure_foundry_vision" as const,
  },
  {
    id: "gemini_vision" as const,
    title: "Gemini Vision (legacy)",
    description: "Google Gemini reads PDF pages directly for classify and extract",
    statusKey: "gemini_vision" as const,
  },
];

export function AiClassificationSettingsPanel({
  value,
  onChange,
  canEdit = true,
}: AiClassificationSettingsPanelProps) {
  const { data: providers } = useTenantQuery({
    queryKey: queryKeys.aiProviders(),
    queryFn: () => api.getAiProviders(),
  });

  const thresholdPct = Math.round((value.autoRouteMinConfidence ?? 0.85) * 100);

  return (
    <Card className="mb-6 border-border/80 p-4 sm:p-5">
      <div className="mb-4 flex items-start gap-3">
        <div className="rounded-md bg-primary/10 p-2 text-primary">
          <Sparkles className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground">AI classification</h3>
          <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
            Documents below the confidence threshold stop for human document-type confirmation
            before amounts and line items are extracted.
          </p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3">
          <span className="block text-xs text-muted-foreground">Document AI provider</span>
          <div className="space-y-2">
            {PROVIDERS.map((provider) => {
              const status = providers?.[provider.statusKey];
              const available = status?.available ?? true;
              const selected = value.documentAiProvider === provider.id;
              return (
                <button
                  key={provider.id}
                  type="button"
                  disabled={!canEdit || !available}
                  onClick={() =>
                    onChange({ ...value, documentAiProvider: provider.id })
                  }
                  className={cn(
                    "w-full rounded-md border px-3 py-2.5 text-left transition-colors",
                    selected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/40",
                    !available && "opacity-60 cursor-not-allowed"
                  )}
                >
                  <div className="text-sm font-medium text-foreground">{provider.title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{provider.description}</div>
                  {!available && status?.reason ? (
                    <div className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">
                      {status.reason}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-3">
          <label htmlFor="auto-route-confidence" className="block text-xs text-muted-foreground">
            Auto-route confidence threshold
          </label>
          <div className="flex items-center gap-3">
            <Input
              id="auto-route-confidence"
              type="number"
              min={50}
              max={100}
              step={1}
              disabled={!canEdit}
              value={thresholdPct}
              onChange={(event) => {
                const pctValue = Number(event.target.value);
                if (Number.isNaN(pctValue)) return;
                onChange({
                  ...value,
                  autoRouteMinConfidence: Math.min(1, Math.max(0, pctValue / 100)),
                });
              }}
              className="w-24"
            />
            <span className="text-sm text-muted-foreground">%</span>
          </div>
          <p className="text-xs text-muted-foreground">
            Default 85%. Lower values auto-route more documents; higher values require more
            manual classification.
          </p>
        </div>
      </div>
    </Card>
  );
}

