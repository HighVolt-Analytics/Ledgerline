import { useEffect, useState } from "react";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { CustomerMastersPanel } from "./CustomerMastersPanel";

const CUSTOMER_SECTIONS = [
  { value: "pending", label: "Pending", testid: "tab-customers-pending" },
  { value: "masters", label: "Customer list", testid: "tab-customers-masters" },
] as const;

type CustomerSection = (typeof CUSTOMER_SECTIONS)[number]["value"];

function resolveSection(raw?: string | null): CustomerSection {
  if (raw === "masters" || raw === "list") return "masters";
  return "pending";
}

export function CustomersTab({
  defaultSection = "pending",
}: {
  defaultSection?: CustomerSection | string | null;
}) {
  const [section, setSection] = useState<CustomerSection>(() => resolveSection(defaultSection));
  const [focusCustomerId, setFocusCustomerId] = useState<string | null>(null);

  useEffect(() => {
    setSection(resolveSection(defaultSection));
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
          testid: row.testid,
          secondary: true,
        }))}
      />

      <PageTabPanel value="pending" active={section} className="mt-0">
        <CustomerMastersPanel
          view="pending"
          onOpenInList={(customerId) => {
            setFocusCustomerId(customerId);
            setSection("masters");
          }}
        />
      </PageTabPanel>
      <PageTabPanel value="masters" active={section} className="mt-0">
        <CustomerMastersPanel view="list" focusCustomerId={focusCustomerId} />
      </PageTabPanel>
    </div>
  );
}
