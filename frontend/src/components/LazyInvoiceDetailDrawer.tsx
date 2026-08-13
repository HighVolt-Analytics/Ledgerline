import { lazy, Suspense, type ComponentProps } from "react";

const InvoiceDetailDrawer = lazy(() =>
  import("@/components/InvoiceDetailDrawer").then((m) => ({
    default: m.InvoiceDetailDrawer,
  }))
);

type InvoiceDetailDrawerProps = ComponentProps<typeof InvoiceDetailDrawer>;

export function LazyInvoiceDetailDrawer(props: InvoiceDetailDrawerProps) {
  return (
    <Suspense fallback={null}>
      <InvoiceDetailDrawer {...props} />
    </Suspense>
  );
}
