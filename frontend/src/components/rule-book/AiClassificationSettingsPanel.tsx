import { Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
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
    id: "claude_vision" as const,
    title: "Claude Vision (Azure AI Foundry)",
    description: "Claude Sonnet reads PDF pages for understand + header extract",
    statusKey: "claude_vision" as const,
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
      <div className="mb-4 flex items-start gap-3 sm:gap-4">
        <div className="rounded-md bg-primary/10 p-2 text-primary shrink-0">
          <Sparkles className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-foreground">AI classification</h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Documents below the confidence threshold stop for human document-type confirmation
                before amounts and line items are extracted.
              </p>
            </div>
            <div className="shrink-0 text-right space-y-1">
              <div className="flex items-center justify-end gap-1.5">
                <Input
                  id="auto-route-confidence"
                  type="number"
                  min={50}
                  max={100}
                  step={1}
                  disabled={!canEdit}
                  aria-label="Auto-route confidence threshold"
                  value={thresholdPct}
                  onChange={(event) => {
                    const pctValue = Number(event.target.value);
                    if (Number.isNaN(pctValue)) return;
                    onChange({
                      ...value,
                      autoRouteMinConfidence: Math.min(1, Math.max(0, pctValue / 100)),
                    });
                  }}
                  className="h-8 w-14 px-2 text-center text-xs"
                />
                <span className="text-xs text-muted-foreground">%</span>
              </div>
              <p className="max-w-[11rem] text-[10px] leading-snug text-muted-foreground">
                Default 85%. Lower auto-routes more; higher needs more manual review.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <span className="block text-xs text-muted-foreground">Document AI provider</span>
        <div className="space-y-2" role="radiogroup" aria-label="Document AI provider">
          {PROVIDERS.map((provider) => {
            const status = providers?.[provider.statusKey];
            const available = status?.available ?? true;
            const selected = value.documentAiProvider === provider.id;
            return (
              <div
                key={provider.id}
                className={cn(
                  "flex w-full items-start gap-3 rounded-md border border-border px-3 py-2.5",
                  !available && "opacity-60"
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">{provider.title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{provider.description}</div>
                  {!available && status?.reason ? (
                    <div className="mt-1 text-[11px] ds-warning-text">{status.reason}</div>
                  ) : null}
                </div>
                <Switch
                  checked={selected}
                  disabled={!canEdit || !available}
                  aria-label={`Use ${provider.title}`}
                  className="mt-0.5"
                  onCheckedChange={(checked) => {
                    if (!checked || !canEdit || !available) return;
                    onChange({ ...value, documentAiProvider: provider.id });
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
