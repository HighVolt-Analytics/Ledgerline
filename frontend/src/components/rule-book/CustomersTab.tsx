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
        Customers use two layers: <strong>masters</strong> (GL, aliases, billing — drives VR12
        registration holds) and <strong>capture registry</strong> (email sender patterns for blob
        routing). Register unknown customers in masters; add capture registry rows manually or when
        promoting from the pending queue (sender is copied from the source invoice).
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
