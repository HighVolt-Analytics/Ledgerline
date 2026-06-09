import { Download, Shield, Upload, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { fmtAud, MOCK_WALLET } from "@/lib/v4MockData";

export function WalletCard() {
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
          <div className="text-lg font-semibold tnum">{fmtAud(MOCK_WALLET.balance)}</div>
          <div className="text-[11px] text-muted-foreground tnum">
            Available {fmtAud(MOCK_WALLET.available)} · last top-up {MOCK_WALLET.lastTopUp}
          </div>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="button-topup">
            <Download className="h-3.5 w-3.5 mr-1" /> Top Up
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-xs" data-testid="button-withdraw">
            <Upload className="h-3.5 w-3.5 mr-1" /> Withdraw
          </Button>
        </div>
      </div>
      <div className="border-t border-border/60 mt-2.5 pt-2 space-y-1 max-h-24 overflow-y-auto">
        {MOCK_WALLET.txns.slice(0, 4).map((txn) => (
          <div key={txn.id} className="flex items-center justify-between text-[11px]">
            <span className="text-muted-foreground truncate pr-2">{txn.label}</span>
            <span
              className={cn(
                "tnum whitespace-nowrap",
                txn.delta < 0 ? "text-muted-foreground" : "text-primary"
              )}
            >
              {txn.delta < 0 ? "" : "+"}
              {fmtAud(txn.delta)}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
