/**
 * Guard for async drawer updates (pipeline poll / approve / reprocess).
 * Prevents a processing invoice from overwriting a newly opened one.
 */
export function shouldApplyDrawerInvoiceUpdate(options: {
  open: boolean;
  activeInvoiceId: number | null | undefined;
  updatedId: number | null | undefined;
}): boolean {
  const { open, activeInvoiceId, updatedId } = options;
  return (
    open &&
    updatedId != null &&
    activeInvoiceId != null &&
    activeInvoiceId === updatedId
  );
}
