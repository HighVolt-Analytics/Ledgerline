import { Download, Shield, Upload, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { WalletCardSkeleton } from "@/components/skeleton/PageSkeletons";
import { useWalletSummary } from "@/hooks/useWalletSummary";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";

export type WalletCardProps = {
  stripeConnected?: boolean;
  stripeLoading?: boolean;
  stripeAvailableTotal?: number;
  stripePendingTotal?: number;
  stripeCurrency?: string;
  stripeLivemode?: boolean;
};

function stripeModeLabel(livemode: boolean | undefined): string {
  if (livemode === true) return "Live";
  if (livemode === false) return "Test";
  return "Sandbox";
}

export function WalletCard({
  stripeConnected = false,
  stripeLoading = false,
  stripeAvailableTotal = 0,
  stripePendingTotal = 0,
  stripeCurrency = "AUD",
  stripeLivemode,
}: WalletCardProps) {
  const { data: wallet, isLoading, error } = useWalletSummary(!stripeConnected);

  if (stripeConnected) {
    const fmt = (value: number) => money(value, stripeCurrency);

    if (stripeLoading) {
      return (
        <Card className="p-4" data-testid="card-wallet">
          <WalletCardSkeleton />
        </Card>
      );
    }

    return (
      <Card
        className="p-4 bg-gradient-to-br from-primary/10 to-transparent border-primary/30"
        data-testid="card-wallet"
      >
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">
            <Wallet className="h-3.5 w-3.5 text-primary" /> Stripe Wallet
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {stripeModeLabel(stripeLivemode)}
            </span>
            <Shield className="h-4 w-4 text-primary/60" />
          </div>
        </div>
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-lg font-semibold tnum">{fmt(stripeAvailableTotal)}</div>
            <div className="text-[11px] text-muted-foreground tnum">
              Available {fmt(stripeAvailableTotal)} · pending {fmt(stripePendingTotal)}
            </div>
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="button-topup" disabled>
              <Download className="h-3.5 w-3.5 mr-1" /> Top Up
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="button-withdraw" disabled>
              <Upload className="h-3.5 w-3.5 mr-1" /> Withdraw
            </Button>
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground border-t border-border/60 mt-2.5 pt-2">
          Balance from connected Stripe account.
        </p>
      </Card>
    );
  }

  if (isLoading && !wallet) {
    return (
      <Card className="p-4" data-testid="card-wallet">
        <WalletCardSkeleton />
      </Card>
    );
  }

  if (error || !wallet) {
    return (
      <Card className="p-4 border-destructive/30" data-testid="card-wallet">
        <p className="text-xs text-destructive">Wallet summary unavailable</p>
      </Card>
    );
  }

  const fmt = (v: number) => money(v, "AUD");

  return (
    <Card
      className="p-4 bg-gradient-to-br from-primary/10 to-transparent border-primary/30"
      data-testid="card-wallet"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">
          <Wallet className="h-3.5 w-3.5 text-primary" /> Stripe Wallet
        </div>
        <Shield className="h-4 w-4 text-primary/60" />
      </div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="text-lg font-semibold tnum">{fmt(wallet.balance)}</div>
          <div className="text-[11px] text-muted-foreground tnum">
            Available {fmt(wallet.available)} · last payment {wallet.last_top_up}
          </div>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="button-topup" disabled>
            <Download className="h-3.5 w-3.5 mr-1" /> Top Up
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="button-withdraw" disabled>
            <Upload className="h-3.5 w-3.5 mr-1" /> Withdraw
          </Button>
        </div>
      </div>
      <div className="border-t border-border/60 mt-2.5 pt-2 space-y-1 max-h-24 overflow-y-auto">
        {wallet.transactions.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">No payment activity yet.</p>
        ) : (
          wallet.transactions.slice(0, 4).map((txn) => (
            <div key={txn.id} className="flex items-center justify-between text-[11px]">
              <span className="text-muted-foreground truncate pr-2">{txn.label}</span>
              <span
                className={cn(
                  "tnum whitespace-nowrap",
                  txn.delta < 0 ? "text-muted-foreground" : txn.delta > 0 ? "text-primary" : "text-muted-foreground"
                )}
              >
                {txn.delta < 0 ? "" : txn.delta > 0 ? "+" : ""}
                {txn.delta === 0 ? "pending" : fmt(txn.delta)}
              </span>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
