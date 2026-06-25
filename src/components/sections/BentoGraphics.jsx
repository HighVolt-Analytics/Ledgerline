/** Graphics for featured bento lifecycle cards */

import { useId } from 'react';
import { AlertTriangle, Check, ChevronDown, Cloud, Fingerprint, Package, Phone, Truck } from 'lucide-react';

function IconTile({ children }) {
  return (
    <div
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] border border-card-border bg-muted shadow-[inset_0_1px_0_hsl(var(--foreground)/0.05)] sm:h-12 sm:w-12"
      aria-hidden="true"
    >
      {children}
    </div>
  );
}

function WhatsAppLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 sm:h-6 sm:w-6" aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#25D366" />
      <path
        fill="#fff"
        d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"
      />
    </svg>
  );
}

function GmailLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 sm:h-6 sm:w-6" aria-hidden="true">
      <path fill="#EA4335" d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L12 9.546l8.073-6.053C21.69 2.28 24 3.434 24 5.457z" />
      <path fill="#FBBC05" d="M12 9.546 3.927 3.493A1.636 1.636 0 0 1 5.5 3h13c.6 0 1.14.327 1.423.848L12 9.546z" />
      <path fill="#34A853" d="M12 16.64 5.455 11.73v9.273h13.09V11.73L12 16.64z" />
      <path fill="#4285F4" d="M24 5.457v6.273L15.455 5.457H24z" />
    </svg>
  );
}

function SlackLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 sm:h-6 sm:w-6" aria-hidden="true">
      <path fill="#E01E5A" d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313z" />
      <path fill="#36C5F0" d="M8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312z" />
      <path fill="#2EB67D" d="M18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.528 2.528 0 0 1-2.52-2.521V2.522A2.528 2.528 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312z" />
      <path fill="#ECB22E" d="M15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.528 2.528 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.528 2.528 0 0 1-2.52-2.523 2.528 2.528 0 0 1 2.52-2.52h6.313A2.528 2.528 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.522h-6.313z" />
    </svg>
  );
}

function OneDriveLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 sm:h-6 sm:w-6" aria-hidden="true">
      <path
        fill="#0078D4"
        d="M18.5 7.5c-.9-2.4-3.2-4-5.9-4-2.5 0-4.7 1.4-5.8 3.5C4.2 7.3 1.5 9.8 1.5 13c0 2.9 2.4 5.3 5.3 5.3h12.7c2.5 0 4.5-2 4.5-4.5 0-2.3-1.7-4.2-4-4.3z"
      />
    </svg>
  );
}

function ViberLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 sm:h-6 sm:w-6" aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#7360F2" />
      <path
        fill="#fff"
        d="M18.2 14.9c-.2-.1-1.4-.7-1.6-.8-.2-.1-.4-.1-.5.1-.1.2-.6.8-.7.9-.1.2-.2.2-.4.1-.2-.1-.9-.4-1.8-1.2-.7-.6-1.1-1.3-1.2-1.5-.1-.2 0-.3.1-.4.1-.1.2-.3.3-.4.1-.1.2-.2.2-.4 0-.1 0-.3-.1-.4 0-.1-.5-1.2-.7-1.7-.2-.4-.4-.4-.6-.4h-.5c-.1 0-.4.1-.6.3-.2.2-.8.8-.8 1.9 0 1.1.8 2.2.9 2.3.1.2 1.6 2.5 4 3.5.6.2 1 .4 1.4.5.6.2 1.1.2 1.5.1.5-.1 1.4-.6 1.6-1.1.2-.5.2-1 .1-1.1-.1-.1-.3-.2-.5-.3z"
      />
      <path
        fill="#fff"
        fillOpacity="0.85"
        d="M12.5 5.5c-3.6 0-6.5 2.4-6.5 5.4 0 1.1.4 2.1 1.1 3 .1.2.1.4 0 .5l-.4 1.5c0 .2.2.4.4.3l1.7-.9c.1-.1.3-.1.4 0 .7.3 1.5.5 2.3.5 3.6 0 6.5-2.4 6.5-5.4s-2.9-5.4-6.5-5.4z"
      />
    </svg>
  );
}

function MobileLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-[#60A5FA] sm:h-5 sm:w-5" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
      <rect x="7" y="2" width="10" height="20" rx="2.5" />
      <circle cx="12" cy="18.5" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  );
}

function WebLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-[#60A5FA] sm:h-5 sm:w-5" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

const topRowLogos = [WhatsAppLogo, GmailLogo, SlackLogo];
const bottomRowLogos = [OneDriveLogo, ViberLogo, MobileLogo];
const middleRowLogos = [GmailLogo, WebLogo, SlackLogo, OneDriveLogo, ViberLogo];

function IconMarqueeRow({ logos, direction, className = '' }) {
  const loop = [...logos, ...logos, ...logos, ...logos];

  return (
    <div className={`received-marquee-mask overflow-hidden ${className}`}>
      <div
        className={`flex w-max gap-2.5 sm:gap-3 ${
          direction === 'left' ? 'received-marquee-animate-left' : 'received-marquee-animate-right'
        }`}
      >
        {loop.map((Logo, i) => (
          <IconTile key={i}>
            <Logo />
          </IconTile>
        ))}
      </div>
    </div>
  );
}

export function ReceivedChannelsGraphic() {
  const fullTrack = [...topRowLogos, ...bottomRowLogos];

  return (
    <div
      className="-mx-5 flex w-[calc(100%+2.5rem)] flex-col gap-2.5 sm:-mx-6 sm:w-[calc(100%+3rem)] sm:gap-3"
      aria-hidden="true"
    >
      <IconMarqueeRow logos={fullTrack} direction="left" className="pl-5 sm:pl-6" />
      <IconMarqueeRow logos={[...middleRowLogos, ...topRowLogos]} direction="right" className="-ml-1 sm:pl-2" />
      <IconMarqueeRow logos={fullTrack} direction="left" className="-ml-2 sm:-ml-1" />
    </div>
  );
}

function ClassifiedTag({ label, icon: Icon, active = false }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-medium leading-none ${
        active
          ? 'border-primary/45 bg-primary text-primary-foreground shadow-[0_0_18px_hsl(var(--primary)/0.28)]'
          : 'border-card-border bg-muted text-muted-foreground'
      }`}
    >
      <Icon className="h-3 w-3 shrink-0" strokeWidth={2} aria-hidden="true" />
      {label}
    </span>
  );
}

function TagMarqueeRow({ tags, direction, className = '' }) {
  const loop = [...tags, ...tags, ...tags, ...tags];

  return (
    <div className={`received-marquee-mask overflow-hidden ${className}`}>
      <div
        className={`flex w-max gap-2 ${
          direction === 'left' ? 'received-marquee-animate-left' : 'received-marquee-animate-right'
        }`}
        style={{ animationDuration: '22s' }}
      >
        {loop.map((tag, i) => (
          <ClassifiedTag key={`${tag.label}-${i}`} {...tag} />
        ))}
      </div>
    </div>
  );
}

const classifiedTagRows = [
  [
    { label: 'Cloud Infra', icon: Cloud, active: true },
    { label: 'Telecom', icon: Phone },
    { label: 'Logistics', icon: Truck },
    { label: 'Office', icon: Package },
    { label: 'Suspense', icon: AlertTriangle },
  ],
  [
    { label: 'Logistics', icon: Truck },
    { label: 'Telecom', icon: Phone, active: true },
    { label: 'Cloud Infra', icon: Cloud },
    { label: 'Freight', icon: Truck },
    { label: 'Office', icon: Package },
  ],
  [
    { label: 'Office', icon: Package },
    { label: 'Suspense', icon: AlertTriangle },
    { label: 'Cloud Infra', icon: Cloud, active: true },
    { label: 'Logistics', icon: Truck },
    { label: 'Telecom', icon: Phone },
  ],
];

export function ClassifiedBandsGraphic() {
  return (
    <div
      className="-mr-5 flex w-[calc(100%+1.25rem)] flex-col justify-center gap-2 sm:-mr-6 sm:w-[calc(100%+1.5rem)] sm:gap-2.5"
      aria-hidden="true"
    >
      <TagMarqueeRow tags={classifiedTagRows[0]} direction="left" className="pl-3 sm:pl-4" />
      <TagMarqueeRow tags={classifiedTagRows[1]} direction="right" className="-ml-2" />
      <TagMarqueeRow tags={classifiedTagRows[2]} direction="left" className="pl-1 sm:pl-2" />
    </div>
  );
}

function DuplicateBackdropCards() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="relative h-[88px] w-[168px] sm:h-[96px] sm:w-[184px]">
        <div className="absolute left-1 top-1/2 h-[64px] w-[96px] -translate-y-1/2 rounded-[14px] border border-[hsl(var(--foreground)/0.06)] bg-[hsl(220_20%_9%)] shadow-[inset_0_1px_0_hsl(var(--foreground)/0.05),0_8px_24px_rgba(0,0,0,0.35)] sm:left-0 sm:h-[70px] sm:w-[104px]">
          <div className="absolute left-2.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full border border-[hsl(var(--foreground)/0.08)] bg-[hsl(220_20%_11%)] sm:left-3 sm:h-8 sm:w-8">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-muted-foreground/50" fill="currentColor" aria-hidden="true">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
            </svg>
          </div>
        </div>
        <div className="absolute right-0 top-1/2 h-[64px] w-[96px] -translate-y-1/2 translate-x-1 rounded-[14px] border border-[hsl(var(--foreground)/0.06)] bg-[hsl(220_20%_10%)] shadow-[inset_0_1px_0_hsl(var(--foreground)/0.05),0_8px_24px_rgba(0,0,0,0.35)] sm:h-[70px] sm:w-[104px]">
          <div className="absolute right-3 top-[calc(50%-9px)] h-[3px] w-[52px] rounded-full bg-foreground/[0.07] sm:w-[58px]" />
          <div className="absolute right-3 top-[calc(50%+7px)] h-[3px] w-[34px] rounded-full bg-foreground/[0.05]" />
        </div>
      </div>
    </div>
  );
}

function DuplicateShield({ idPrefix = 'dup' }) {
  return (
    <div className="duplicate-shield-wrap relative z-10">
      <div className="relative">
        <svg viewBox="0 0 80 96" className="relative z-10 h-[80px] w-[68px] drop-shadow-[0_12px_28px_rgba(0,0,0,0.45)] sm:h-[88px] sm:w-[74px]" aria-hidden="true">
          <defs>
            <linearGradient id={`${idPrefix}-keyhole-grad`} x1="40" y1="28" x2="40" y2="56" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="hsl(var(--accent-glow))" />
              <stop offset="55%" stopColor="hsl(195 95% 55%)" />
              <stop offset="100%" stopColor="hsl(var(--primary))" />
            </linearGradient>
            <linearGradient id={`${idPrefix}-shield-face`} x1="40" y1="8" x2="40" y2="88" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="hsl(220 18% 14%)" />
              <stop offset="100%" stopColor="hsl(220 22% 8%)" />
            </linearGradient>
          </defs>
          <path
            d="M40 3 L70 16 V46 C70 65 57 80 40 93 C23 80 10 65 10 46 V16 Z"
            fill="hsl(220 20% 7%)"
            stroke="hsl(var(--foreground) / 0.1)"
            strokeWidth="1.25"
          />
          <path
            d="M40 7 L66 18.5 V46 C66 62.5 55.5 75.5 40 87 C24.5 75.5 14 62.5 14 46 V18.5 Z"
            fill={`url(#${idPrefix}-shield-face)`}
            stroke="hsl(var(--foreground) / 0.07)"
            strokeWidth="1"
          />
          <path
            d="M40 7 L66 18.5 V22 C50 14 30 14 14 22 V18.5 Z"
            fill="hsl(var(--foreground) / 0.04)"
          />
          <g className="duplicate-keyhole-glow">
            <circle cx="40" cy="37" r="8" fill={`url(#${idPrefix}-keyhole-grad)`} />
            <rect x="36" y="43.5" width="8" height="12" rx="4" fill={`url(#${idPrefix}-keyhole-grad)`} />
          </g>
        </svg>
        <div
          className="duplicate-fingerprint-scan absolute inset-0 z-20 flex items-center justify-center"
          style={{ clipPath: 'polygon(50% 2%, 91% 19%, 91% 55%, 50% 98%, 9% 55%, 9% 19%)' }}
        >
          <Fingerprint className="h-8 w-8 text-primary sm:h-9 sm:w-9" strokeWidth={1.5} aria-hidden="true" />
        </div>
        <div
          className="duplicate-scan-sweep pointer-events-none absolute inset-0 z-30 overflow-hidden"
          style={{ clipPath: 'polygon(50% 2%, 91% 19%, 91% 55%, 50% 98%, 9% 55%, 9% 19%)' }}
        >
          <div className="h-7 w-full bg-gradient-to-b from-transparent via-[hsl(var(--accent-glow)/0.4)] to-transparent" />
        </div>
      </div>
    </div>
  );
}

export function DuplicateCheckGraphic({ layout = 'bento' }) {
  const id = useId().replace(/:/g, '');
  const isHeader = layout === 'header';

  return (
    <div
      className={
        isHeader
          ? 'group relative mx-auto flex h-[140px] w-full max-w-[300px] items-center justify-center rounded-2xl border border-[hsl(var(--foreground)/0.05)] bg-[hsl(220_28%_5%)] shadow-[inset_0_1px_0_hsl(var(--foreground)/0.04)] sm:h-[148px]'
          : 'relative mx-auto flex h-[124px] w-full max-w-[210px] items-center justify-center rounded-2xl border border-[hsl(var(--foreground)/0.05)] bg-[hsl(220_28%_5%)] shadow-[inset_0_1px_0_hsl(var(--foreground)/0.04)] sm:h-[132px] sm:max-w-[228px]'
      }
      aria-hidden="true"
    >
      <DuplicateBackdropCards />
      <DuplicateShield idPrefix={id} />
    </div>
  );
}

export function PaymentApprovedGraphic() {
  return (
    <div className="flex h-full min-h-[128px] items-center justify-center px-1" aria-hidden="true">
      <div className="payment-approved-panel relative w-full max-w-[240px] overflow-hidden rounded-2xl border border-card-border/80 bg-[hsl(220_30%_5%)] px-4 py-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] sm:px-5 sm:py-5">
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-20 rounded-b-2xl opacity-70 transition-opacity duration-400 group-hover:opacity-100"
          style={{
            background: 'radial-gradient(ellipse 80% 80% at 50% 100%, hsl(250 70% 30% / 0.45), transparent 70%)',
          }}
        />
        <div className="relative flex items-start justify-between gap-3">
          <div className="flex items-baseline gap-0.5 font-medium tracking-tight text-foreground">
            <span className="text-sm text-muted-foreground">$</span>
            <span className="text-[1.65rem] leading-none sm:text-3xl">4,182</span>
            <span className="text-sm text-muted-foreground">.00</span>
            <span className="payment-amount-cursor ml-0.5 inline-block h-5 w-px bg-primary sm:h-6" />
          </div>
          <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-card-border bg-muted/80 px-2 py-1 text-[10px] text-foreground">
            <span>USD</span>
            <ChevronDown className="h-3 w-3 text-muted-foreground" strokeWidth={2} />
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#1a3a8a] text-[8px] text-white">
              ★
            </span>
          </div>
        </div>
        <div className="relative mt-5 flex items-center gap-2 text-lg font-medium tracking-tight text-foreground sm:text-xl">
          Successfully paid
          <span className="payment-check-pop flex h-5 w-5 items-center justify-center rounded-full bg-[hsl(270_70%_55%)] text-white">
            <Check className="h-3 w-3" strokeWidth={3} />
          </span>
        </div>
      </div>
    </div>
  );
}

const bentoGraphicConfig = {
  Received: { component: ReceivedChannelsGraphic, placement: 'center' },
  Classified: { component: ClassifiedBandsGraphic, placement: 'right' },
  'Duplicate-checked': { component: DuplicateCheckGraphic, placement: 'right' },
  'Payment approved': { component: PaymentApprovedGraphic, placement: 'right' },
};

export function getBentoGraphicConfig(title) {
  return bentoGraphicConfig[title] ?? null;
}
