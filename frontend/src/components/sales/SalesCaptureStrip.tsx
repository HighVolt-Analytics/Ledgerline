import { Link } from "react-router-dom";
import { BookOpen, Landmark, TrendingUp, Users } from "lucide-react";
import { Card } from "@/components/ui/card";

export function SalesCaptureStrip({ activeRuleCount = 0 }: { activeRuleCount?: number }) {
  return (
    <Card className="mb-5 p-3 flex flex-wrap items-center gap-3 text-sm">
      <div className="flex items-center gap-2 text-muted-foreground">
        <TrendingUp className="h-4 w-4 text-primary shrink-0" />
        <span>
          {activeRuleCount > 0
            ? `${activeRuleCount} active sales rule${activeRuleCount === 1 ? "" : "s"}`
            : "No active sales rules — add rules in Rule Book"}
        </span>
      </div>
      <Link
        to="/creations?tab=customers&customersSection=capture"
        className="inline-flex items-center gap-1.5 text-primary hover:underline text-sm"
        data-testid="link-sales-customers"
      >
        <Users className="h-3.5 w-3.5" />
        Customer capture
      </Link>
      <Link
        to="/collections"
        className="inline-flex items-center gap-1.5 text-primary hover:underline text-sm"
        data-testid="link-sales-collections"
      >
        <Landmark className="h-3.5 w-3.5" />
        Collections queue
      </Link>
      <Link
        to="/rules"
        className="inline-flex items-center gap-1.5 text-primary hover:underline text-sm ml-auto"
        data-testid="link-sales-rule-book"
      >
        <BookOpen className="h-3.5 w-3.5" />
        Sales GL rules
      </Link>
    </Card>
  );
}
