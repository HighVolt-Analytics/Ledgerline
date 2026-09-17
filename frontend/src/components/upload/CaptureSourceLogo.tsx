import type { ReactNode } from "react";
import cloudUploadIcon from "@/assets/channel-icons/cloud-upload.png";
import mobileAppIcon from "@/assets/channel-icons/mobile-app.svg";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import type { InvoiceSource } from "@/lib/invoice";

const ICON_SIZE = 16;

function ChannelMark({
  size = ICON_SIZE,
  children,
}: {
  size?: number;
  children: ReactNode;
}) {
  return (
    <span
      className="integration-brand-icon"
      aria-hidden
      style={{ width: size, height: size }}
    >
      {children}
    </span>
  );
}

/** Same marks as the Upload page channel tabs. */
export function CaptureSourceLogo({
  source,
  size = ICON_SIZE,
}: {
  source: InvoiceSource;
  size?: number;
}) {
  if (source === "email") {
    return <IntegrationBrandIcon id="graph" size={size} />;
  }
  if (source === "slack") {
    return <IntegrationBrandIcon id="slack" size={size} />;
  }
  if (source === "whatsapp") {
    return <IntegrationBrandIcon id="whatsapp" size={size} />;
  }
  if (source === "viber") {
    return <IntegrationBrandIcon id="viber" size={size} />;
  }
  if (source === "app") {
    return (
      <ChannelMark size={size}>
        <img src={mobileAppIcon} alt="" draggable={false} />
      </ChannelMark>
    );
  }
  return (
    <ChannelMark size={size}>
      <img src={cloudUploadIcon} alt="" draggable={false} />
    </ChannelMark>
  );
}
