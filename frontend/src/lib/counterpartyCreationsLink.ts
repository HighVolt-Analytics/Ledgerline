import { withRouterBasename } from "@/lib/routerBasename";

export const COUNTERPARTY_HEADER_HOVER_HINT = "Click to go to Vendors in Creations";

export function creationsVendorsHref(): string {
  return withRouterBasename("/creations?tab=vendors");
}
