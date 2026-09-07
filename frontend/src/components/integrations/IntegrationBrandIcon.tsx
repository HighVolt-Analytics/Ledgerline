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
  siSlack,
  siViber,
  siWhatsapp,
  siXero,
} from "simple-icons";
import { cn } from "@/lib/cn";
import type { IntegrationBrandId } from "./types";

const ICONS: Record<IntegrationBrandId, SimpleIcon> = {
  graph: siMicrosoftoutlook,
  whatsapp: siWhatsapp,
  slack: siSlack,
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

export function IntegrationBrandIcon({
  id,
  className,
  size,
}: {
  id: IntegrationBrandId;
  className?: string;
  size?: number;
}) {
  const icon = ICONS[id];
  if (!icon) return null;
  return <BrandSvg icon={icon} className={className} size={size} />;
}

export type { IntegrationBrandId };
