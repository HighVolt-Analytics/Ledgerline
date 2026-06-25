import { Coins } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NumericInput } from "@/components/ui/numeric-input";
import { useAuth } from "@/context/AuthContext";
import { useBilling, useBillingMutations } from "@/hooks/useBilling";
import { cn } from "@/lib/cn";

const USAGE = [
  { action: "OCR Parse a document", credits: 3 },
  { action: "GST Input Credit validation", credits: 1 },
  { action: "Post to Ledger", credits: 5 },
  { action: "Vault storage per GB/month", credits: 2 },
];

export function BillingPage() {
  const { user } = useAuth();
  const { data: billing, isLoading, error } = useBilling(Boolean(user));
  const { updateSettings, purchasePack } = useBillingMutations();

  if (!user) {
    return (
      <div>
        <PageHeader title="Billing & Credits" subtitle="Pay-as-you-go processing credits for your organisation." />
        <p className="text-sm text-muted-foreground">Sign in to manage billing.</p>
      </div>
    );
  }

  if (isLoading && !billing) {
    return (
      <div>
        <PageHeader title="Billing & Credits" subtitle="Pay-as-you-go processing credits for your organisation." />
        <PageLoader label="Loading billing…" />
      </div>
    );
  }

  if (error || !billing) {
    return (
      <div>
        <PageHeader title="Billing & Credits" subtitle="Pay-as-you-go processing credits for your organisation." />
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : "Failed to load billing"}
        </p>
      </div>
    );
  }

  const currentPackName =
    billing.packs.find((p) => p.id === billing.current_pack)?.name ?? "Starter";

  return (
    <div>
      <PageHeader
        title="Billing & Credits"
        subtitle="Pay-as-you-go processing credits for your organisation."
      />

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <Card className="p-5 lg:col-span-1 bg-gradient-to-br from-primary/8 to-transparent border-primary/20">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <Coins className="h-4 w-4 text-primary" />
            Credit balance
          </div>
          <p className="text-3xl font-semibold tnum" data-testid="text-credit-balance">
            {billing.balance.toLocaleString()}
          </p>
          <p className="text-xs text-muted-foreground mt-1">Current pack: {currentPackName}</p>
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <p className="text-sm">Auto-recharge</p>
                <p className="text-xs text-muted-foreground">
                  Top up this organisation automatically when credits run low.
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={billing.auto_recharge}
                data-testid="toggle-auto-recharge"
                onClick={() => void updateSettings({ auto_recharge: !billing.auto_recharge })}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 rounded-full border border-transparent transition-colors",
                  billing.auto_recharge ? "bg-primary" : "bg-input"
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm transition-transform mt-0.5",
                    billing.auto_recharge ? "translate-x-4" : "translate-x-0.5"
                  )}
                />
              </button>
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                Recharge at
                <span className="font-medium mx-1">{billing.threshold.toLocaleString()} credits</span>
                when balance drops below threshold.
              </p>
              <NumericInput
                value={billing.threshold}
                onValueChange={(n) => {
                  if (n != null) void updateSettings({ threshold: n });
                }}
                wrapperClassName="w-20 shrink-0"
                className="h-7 text-xs"
                data-testid="input-threshold"
              />
            </div>
          </div>
        </Card>

        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold mb-3">Credit usage</h2>
          <ul className="space-y-2">
            {USAGE.map((row) => (
              <li
                key={row.action}
                className="flex items-center justify-between text-sm py-1.5 border-b border-border last:border-0"
              >
                <span>{row.action}</span>
                <span className="tnum text-muted-foreground">{row.credits} credits</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <h2 className="text-sm font-semibold mb-3">Credit packs</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {billing.packs.map((pack) => (
          <Card
            key={pack.id}
            className={cn(
              "p-4 flex flex-col",
              pack.popular && "border-primary/40 ring-1 ring-primary/20"
            )}
            data-testid={`pack-${pack.id}`}
          >
            {pack.popular && (
              <Badge variant="outline" className="w-fit mb-2 border-primary/30 text-primary">
                Popular
              </Badge>
            )}
            <p className="font-semibold">{pack.name}</p>
            <p className="text-2xl font-semibold tnum mt-1">
              {pack.credits.toLocaleString()}
              <span className="text-sm font-normal text-muted-foreground ml-1">credits</span>
            </p>
            <p className="text-sm text-muted-foreground mt-1">A${pack.price_aud}</p>
            <Button
              className="mt-4 w-full"
              variant={pack.popular ? "default" : "outline"}
              onClick={() => void purchasePack(pack.id)}
              data-testid={`button-buy-${pack.id}`}
            >
              Buy pack
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}
