import { Link } from "react-router-dom";

import { Card } from "@/components/ui/card";

export function NoBillProcessingTaxNote() {
  return (
    <Card className="w-full p-8" data-testid="tax-rates-connect-note">
      <p className="text-center text-sm text-muted-foreground">
        Connect a bill processing platform to view tax rates.{" "}
        <Link to="/integrations" className="text-primary hover:underline">
          Open Integrations
        </Link>
      </p>
    </Card>
  );
}
