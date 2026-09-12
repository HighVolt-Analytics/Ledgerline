import { Globe, Smartphone } from 'lucide-react';
import viber from '../../assets/integrations/viber.svg';
import whatsapp from '../../assets/integrations/whatsapp.svg';

export function WhatsAppIcon({ className = 'h-7 w-7' }) {
  return <img src={whatsapp} alt="" className={className} />;
}

export function ViberIcon({ className = 'h-7 w-7' }) {
  return <img src={viber} alt="" className={className} />;
}

export function MobileAppIcon({ className = 'h-7 w-7' }) {
  return <Smartphone className={`${className} text-[#3B82F6]`} strokeWidth={1.75} aria-hidden="true" />;
}

export function WebPortalIcon({ className = 'h-7 w-7' }) {
  return <Globe className={`${className} text-[#F59E0B]`} strokeWidth={1.75} aria-hidden="true" />;
}

export const captureChannelIcons = {
  WhatsApp: WhatsAppIcon,
  Viber: ViberIcon,
  'Mobile app': MobileAppIcon,
  'Web portal': WebPortalIcon,
};
