import { useEffect, useState } from "react";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { CustomerMastersPanel } from "./CustomerMastersPanel";
import { CustomerRegistryPanel } from "./CustomerRegistryPanel";

const CUSTOMER_SECTIONS = [
  { value: "capture", label: "Pending" },
  { value: "masters", label: "Customer list" },
] as const;

type CustomerSection = (typeof CUSTOMER_SECTIONS)[number]["value"];

export function CustomersTab({
  defaultSection = "capture",
}: {
  defaultSection?: CustomerSection | string | null;
}) {
  const initialSection: CustomerSection =
    defaultSection === "masters" ? "masters" : "capture";
  const [section, setSection] = useState<CustomerSection>(initialSection);

  useEffect(() => {
    setSection(defaultSection === "masters" ? "masters" : "capture");
  }, [defaultSection]);

  return (
    <div className="space-y-4" data-testid="customers-tab">
      <PageTabs
        value={section}
        onChange={(value) => setSection(value as CustomerSection)}
        data-testid="customers-section-tabs"
        tabs={CUSTOMER_SECTIONS.map((row) => ({
          value: row.value,
          label: row.label,
          testid: `tab-customers-${row.value}`,
          secondary: true,
        }))}
      />

      <PageTabPanel value="capture" active={section} className="mt-0">
        <CustomerRegistryPanel />
      </PageTabPanel>
      <PageTabPanel value="masters" active={section} className="mt-0">
        <CustomerMastersPanel />
      </PageTabPanel>
    </div>
  );
}
