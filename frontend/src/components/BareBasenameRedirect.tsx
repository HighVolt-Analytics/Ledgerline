import { useLayoutEffect } from "react";
import { getRouterBasename, normalizeBareBasenameUrl } from "@/lib/routerBasename";

/** Client-side fallback when /ledgerlink is served without a trailing slash. */
export function BareBasenameRedirect() {
  const basename = getRouterBasename();

  useLayoutEffect(() => {
    normalizeBareBasenameUrl();
  }, [basename]);

  return null;
}
