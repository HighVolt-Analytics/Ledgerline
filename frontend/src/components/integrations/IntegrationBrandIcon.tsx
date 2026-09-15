import type { SimpleIcon } from "simple-icons";
import {
  siAzuredataexplorer,
  siMicrosoftazure,
  siMicrosoftoutlook,
  siMyob,
  siPostgresql,
  siQuickbooks,
  siRedis,
  siStripe,
  siViber,
  siWhatsapp,
  siXero,
} from "simple-icons";
import { cn } from "@/lib/cn";
import type { IntegrationBrandId } from "./types";

const ICONS: Record<Exclude<IntegrationBrandId, "slack">, SimpleIcon> = {
  graph: siMicrosoftoutlook,
  whatsapp: siWhatsapp,
  viber: siViber,
  blob: siMicrosoftazure,
  di: siAzuredataexplorer,
  postgres: siPostgresql,
  redis: siRedis,
  appinsights: siAzuredataexplorer,
  xero: siXero,
  qbo: siQuickbooks,
  myob: siMyob,
  stripe: siStripe,
};

function BrandSvg({
  icon,
  className,
  size,
}: {
  icon: SimpleIcon;
  className?: string;
  size?: number;
}) {
  return (
    <span
      className={cn("integration-brand-icon", className)}
      aria-hidden
      style={size ? { width: size, height: size } : undefined}
    >
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" role="img">
        <title>{icon.title}</title>
        <path fill={`#${icon.hex}`} style={{ fill: `#${icon.hex}` }} d={icon.path} />
      </svg>
    </span>
  );
}

function SlackBrandSvg({ className, size }: { className?: string; size?: number }) {
  return (
    <span
      className={cn("integration-brand-icon", className)}
      aria-hidden
      style={size ? { width: size, height: size } : undefined}
    >
      <svg viewBox="0 0 127 127" xmlns="http://www.w3.org/2000/svg" role="img">
        <title>Slack</title>
        <path
          fill="#E01E5A"
          d="M27.2 80c0 7.3-5.9 13.2-13.2 13.2C6.7 93.2.8 87.3.8 80c0-7.3 5.9-13.2 13.2-13.2h13.2V80zm6.6 0c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2v33c0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V80z"
        />
        <path
          fill="#36C5F0"
          d="M47 27.2c-7.3 0-13.2-5.9-13.2-13.2C33.8 6.7 39.7.8 47 .8c7.3 0 13.2 5.9 13.2 13.2v13.2H47zm0 6.6c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H14c-7.3 0-13.2-5.9-13.2-13.2 0-7.3 5.9-13.2 13.2-13.2H47z"
        />
        <path
          fill="#2EB67D"
          d="M99.8 47c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H99.8V47zm-6.6 0c0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V14c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2v33z"
        />
        <path
          fill="#ECB22E"
          d="M80 99.8c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V99.8H80zm0-6.6c-7.3 0-13.2-5.9-13.2-13.2 0-7.3 5.9-13.2 13.2-13.2h33c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H80z"
        />
      </svg>
    </span>
  );
}

export function IntegrationBrandIcon({
  id,
  className,
  size,
}: {
  id: IntegrationBrandId;
  className?: string;
  size?: number;
}) {
  if (id === "slack") {
    return <SlackBrandSvg className={className} size={size} />;
  }
  const icon = ICONS[id];
  if (!icon) return null;
  return <BrandSvg icon={icon} className={className} size={size} />;
}

export type { IntegrationBrandId };
