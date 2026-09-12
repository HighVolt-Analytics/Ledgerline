/** Graphics for featured bento lifecycle cards */

import { useId } from 'react';
import { AlertTriangle, Check, ChevronDown, Cloud, Fingerprint, Package, Phone, Truck } from 'lucide-react';
import gmail from '../../assets/integrations/gmail.svg';
import googledrive from '../../assets/integrations/googledrive.svg';
import slack from '../../assets/integrations/slack.svg';
import viber from '../../assets/integrations/viber.svg';
import whatsapp from '../../assets/integrations/whatsapp.svg';

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

function BrandLogo({ src }) {
  return <img src={src} alt="" className="h-5 w-5 object-contain sm:h-6 sm:w-6" />;
}

function WhatsAppLogo() {
  return <BrandLogo src={whatsapp} />;
}

function GmailLogo() {
  return <BrandLogo src={gmail} />;
}

function SlackLogo() {
  return <BrandLogo src={slack} />;
}

function OneDriveLogo() {
  return <BrandLogo src={googledrive} />;
}

function ViberLogo() {
  return <BrandLogo src={viber} />;
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

function BentoFeatureImage({ src, shift = 'default', zoom = false }) {
  const classes = [
    'bento-card-image',
    shift === 'high' && 'bento-card-image--high',
    zoom === true && 'bento-card-image--zoom',
    zoom === 'doc' && 'bento-card-image--zoom-doc',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes} aria-hidden="true">
      <img src={src} alt="" className="bento-card-image__img" />
      <div className="bento-card-image__blend" aria-hidden="true" />
    </div>
  );
}

export function ReceivedChannelsGraphic() {
  return <BentoFeatureImage src="/feature%20images/received%20image.png" />;
}

export function ExtractedGraphic() {
  return <BentoFeatureImage src="/feature%20images/extract%20(2).png" zoom="doc" />;
}

export function MatchedGraphic() {
  return <BentoFeatureImage src="/feature%20images/EXTRACT.png" />;
}

export function ClassifiedGraphic() {
  return <BentoFeatureImage src="/feature%20images/CLASSIFIED.png" zoom />;
}

export function DuplicateCheckImageGraphic() {
  return <BentoFeatureImage src="/feature%20images/duplicate%20(2).png" />;
}

export function PendingApprovalGraphic() {
  return <BentoFeatureImage src="/feature%20images/PENDING.png" />;
}

export function ApprovedGraphic() {
  return <BentoFeatureImage src="/feature%20images/APPROVED.png" zoom />;
}

export function ThreeWayMatchedGraphic() {
  return <BentoFeatureImage src="/feature%20images/3-WAY.png" />;
}

export function PaymentQueuedGraphic() {
  return <BentoFeatureImage src="/feature%20images/payment%20que.png" />;
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
    <div className="flex h-full w-full flex-col justify-start gap-2 pt-2 sm:gap-2.5 sm:pt-3" aria-hidden="true">
      <TagMarqueeRow tags={classifiedTagRows[0]} direction="left" className="pl-3 sm:pl-4" />
      <TagMarqueeRow tags={classifiedTagRows[1]} direction="right" />
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
    <div className="flex h-full w-full items-center justify-center px-2" aria-hidden="true">
      <div className="payment-approved-panel relative w-full max-w-[240px] overflow-hidden rounded-2xl border border-card-border/80 bg-[hsl(220_30%_5%)] px-4 py-3 shadow-[0_12px_40px_rgba(0,0,0,0.45)] sm:px-5 sm:py-4">
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
  Received: { component: ReceivedChannelsGraphic, type: 'image' },
  Extracted: { component: ExtractedGraphic, type: 'image' },
  Matched: { component: MatchedGraphic, type: 'image' },
  Classified: { component: ClassifiedGraphic, type: 'image' },
  'Duplicate-checked': { component: DuplicateCheckImageGraphic, type: 'image' },
  'Pending approval': { component: PendingApprovalGraphic, type: 'image' },
  Approved: { component: ApprovedGraphic, type: 'image' },
  'Three-way matched': { component: ThreeWayMatchedGraphic, type: 'image' },
  'Payment queued': { component: PaymentQueuedGraphic, type: 'image' },
  'Payment approved': { component: PaymentApprovedGraphic },
};

export function getBentoGraphicConfig(title) {
  return bentoGraphicConfig[title] ?? null;
}
