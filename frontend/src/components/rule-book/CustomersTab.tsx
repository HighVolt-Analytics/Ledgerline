import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { CustomerMastersPanel } from "./CustomerMastersPanel";
import { CustomerRegistryPanel } from "./CustomerRegistryPanel";

const CUSTOMER_SECTIONS = [
  { value: "masters", label: "Customer masters" },
  { value: "capture", label: "Capture registry" },
] as const;

type CustomerSection = (typeof CUSTOMER_SECTIONS)[number]["value"];

export function CustomersTab({
  defaultSection = "masters",
}: {
  defaultSection?: CustomerSection | string | null;
}) {
  const initialSection: CustomerSection =
    defaultSection === "capture" ? "capture" : "masters";
  const [section, setSection] = useState<CustomerSection>(initialSection);

  useEffect(() => {
    setSection(defaultSection === "capture" ? "capture" : "masters");
  }, [defaultSection]);

  return (
    <div className="space-y-4" data-testid="customers-tab">
      <Card className="p-3 text-sm text-muted-foreground">
        Customers are split into two layers: <strong>masters</strong> (GL, aliases, billing for
        sales routing) and <strong>capture registry</strong> (email sender patterns for inbound
        documents). Both are needed for full sales automation.
      </Card>

      <PageTabs
        value={section}
        onChange={(value) => setSection(value as CustomerSection)}
        variant="underline"
        tabs={CUSTOMER_SECTIONS.map((row) => ({
          value: row.value,
          label: row.label,
          testid: `tab-customers-${row.value}`,
        }))}
      />

      <PageTabPanel value="masters" active={section} className="mt-0">
        <CustomerMastersPanel />
      </PageTabPanel>
      <PageTabPanel value="capture" active={section} className="mt-0">
        <CustomerRegistryPanel />
      </PageTabPanel>
    </div>
  );
}
