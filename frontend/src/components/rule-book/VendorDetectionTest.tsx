import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FlaskConical } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { BUSINESS_REGISTRATION_NUMBER_LABEL } from "@/lib/format";
import { detectVendorFromSample } from "@/lib/v4RuleBookLogic";
import type { VendorDetectionConfig, VendorMaster } from "@/lib/v4RuleBookTypes";
import { ConfidenceBar } from "./ConfidenceBar";
import { FieldLabel } from "./FieldLabel";

const DEFAULT_SAMPLE = {
  name: "Amazon AWS",
  abn: "98765432101",
  bsb: "062-001",
  accountNumber: "12345678",
  address: "Sydney NSW",
};

export function VendorDetectionTest({
  vendors,
  config,
}: {
  vendors: VendorMaster[];
  config: VendorDetectionConfig;
}) {
  const [open, setOpen] = useState(false);
  const [sample, setSample] = useState(DEFAULT_SAMPLE);

  const result = useMemo(
    () => detectVendorFromSample(sample, vendors, config),
    [sample, vendors, config]
  );

  const matched = result.confidence >= config.threshold && result.vendor !== null;

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center justify-between gap-2 p-3 text-left"
        onClick={() => setOpen((v) => !v)}
        data-testid="toggle-detection-test"
      >
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Vendor detection test</h3>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {open && (
        <div className="border-t border-border bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground mb-3">
            Enter a sample inbound invoice. Confidence is computed live from your weights.
          </p>

          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-2.5 mb-3">
            <FieldLabel label="Vendor name">
              <Input
                value={sample.name}
                onChange={(e) => setSample({ ...sample, name: e.target.value })}
                className="h-8 text-xs"
              />
            </FieldLabel>
            <FieldLabel label={BUSINESS_REGISTRATION_NUMBER_LABEL}>
              <Input
                value={sample.abn}
                onChange={(e) => setSample({ ...sample, abn: e.target.value })}
                className="h-8 text-xs font-mono"
              />
            </FieldLabel>
            <FieldLabel label="BSB">
              <Input
                value={sample.bsb}
                onChange={(e) => setSample({ ...sample, bsb: e.target.value })}
                className="h-8 text-xs font-mono"
              />
            </FieldLabel>
            <FieldLabel label="Account #">
              <Input
                value={sample.accountNumber}
                onChange={(e) => setSample({ ...sample, accountNumber: e.target.value })}
                className="h-8 text-xs font-mono"
              />
            </FieldLabel>
            <FieldLabel label="Address">
              <Input
                value={sample.address}
                onChange={(e) => setSample({ ...sample, address: e.target.value })}
                className="h-8 text-xs"
              />
            </FieldLabel>
          </div>

          <div
            className={cn(
              "rounded-lg border p-3 flex items-center justify-between gap-3 flex-wrap",
              matched
                ? "border-primary/30 bg-primary/5"
                : "border-destructive/30 bg-destructive/5"
            )}
            data-testid="detection-test-result"
          >
            <div className="min-w-0">
              {matched && result.vendor ? (
                <div className="text-sm font-medium">
                  Matched: <span className="text-primary">{result.vendor.name}</span>
                </div>
              ) : (
                <div className="text-sm font-medium text-destructive">
                  NEW VENDOR — flag for registration
                </div>
              )}
              <div className="text-xs text-muted-foreground">
                Threshold {config.threshold}% ·{" "}
                {matched ? "auto-matched, defaults applied" : "below threshold"}
              </div>
            </div>
            <div className="w-40">
              <ConfidenceBar value={result.confidence} />
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
