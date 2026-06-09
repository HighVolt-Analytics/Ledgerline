import { useState } from "react";
import { Coins } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NumericInput } from "@/components/ui/numeric-input";
import { cn } from "@/lib/cn";

const CREDIT_PACKS = [
  { id: "starter", name: "Starter", credits: 500, priceAUD: 49 },
  { id: "team", name: "Team", credits: 2500, priceAUD: 199, popular: true },
  { id: "growth", name: "Growth", credits: 10000, priceAUD: 699 },
  { id: "scale", name: "Scale", credits: 50000, priceAUD: 2999 },
];

const USAGE = [
  { action: "OCR Parse a document", credits: 3 },
  { action: "GST Input Credit validation", credits: 1 },
  { action: "Publish to Ledger", credits: 5 },
  { action: "Vault storage per GB/month", credits: 2 },
];

export function BillingPage() {
  const [balance, setBalance] = useState(500);
  const [autoRecharge, setAutoRecharge] = useState(false);
  const [currentPack, setCurrentPack] = useState<string>("starter");
  const [threshold, setThreshold] = useState<number>(100);

  const buyPack = (packId: string, credits: number) => {
    setBalance((b) => b + credits);
    setCurrentPack(packId);
  };

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
            {balance.toLocaleString()}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Current pack: {CREDIT_PACKS.find((p) => p.id === currentPack)?.name ?? "Starter"}
          </p>
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
                aria-checked={autoRecharge}
                data-testid="toggle-auto-recharge"
                onClick={() => setAutoRecharge((v) => !v)}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 rounded-full border border-transparent transition-colors",
                  autoRecharge ? "bg-primary" : "bg-input"
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm transition-transform mt-0.5",
                    autoRecharge ? "translate-x-4" : "translate-x-0.5"
                  )}
                />
              </button>
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                Recharge at
                <span className="font-medium mx-1">{threshold.toLocaleString()} credits</span>
                when balance drops below threshold.
              </p>
              <NumericInput
                value={threshold}
                onValueChange={(n) => setThreshold(n ?? 0)}
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
        {CREDIT_PACKS.map((pack) => (
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
            <p className="text-sm text-muted-foreground mt-1">A${pack.priceAUD}</p>
            <Button
              className="mt-4 w-full"
              variant={pack.popular ? "default" : "outline"}
              onClick={() => buyPack(pack.id, pack.credits)}
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
