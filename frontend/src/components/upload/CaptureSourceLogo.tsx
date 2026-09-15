import { CloudUpload, Smartphone } from "lucide-react";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import type { InvoiceSource } from "@/lib/invoice";

const ICON_SIZE = 16;

/** Same marks as the Upload page channel tabs. */
export function CaptureSourceLogo({ source }: { source: InvoiceSource }) {
  if (source === "email") {
    return <IntegrationBrandIcon id="graph" size={ICON_SIZE} />;
  }
  if (source === "slack") {
    return <IntegrationBrandIcon id="slack" size={ICON_SIZE} />;
  }
  if (source === "whatsapp") {
    return <IntegrationBrandIcon id="whatsapp" size={ICON_SIZE} />;
  }
  if (source === "viber") {
    return <IntegrationBrandIcon id="viber" size={ICON_SIZE} />;
  }
  if (source === "app") {
    return <Smartphone className="h-4 w-4 text-primary" />;
  }
  return <CloudUpload className="h-4 w-4 text-primary" />;
}
