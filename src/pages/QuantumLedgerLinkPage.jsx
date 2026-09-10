import { useEffect, useRef, useState } from 'react';
import {
  Fingerprint,
  FileCheck,
  GitCompare,
  Users,
  Shield,
  Lock,
  Inbox,
  Keyboard,
  AlertTriangle,
  FolderOpen,
  Download,
  Tags,
  ScanText,
  CheckCircle2,
  Banknote,
  MousePointerClick,
  Camera,
  ClipboardCheck,
  Wallet,
  User,
  DollarSign,
  Calculator,
  FileSpreadsheet,
  SearchCheck,
  Check,
  X,
} from 'lucide-react';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';
import { WorldMap } from '../components/ui/WorldMap';
import IntegrationsSection from '../components/sections/IntegrationsSection';
import { externalLinks } from '../data/navigation';
import { controls } from '../data/sections';
import '../qll.css';

const YOUTUBE_EMBED =
  'https://www.youtube-nocookie.com/embed/0luxUk3VtgA?autoplay=1&rel=0&modestbranding=1';

const controlIcons = {
  C1: Fingerprint,
  C2: FileCheck,
  C3: GitCompare,
  C4: Users,
  C5: Shield,
  C6: Lock,
};

const productCards = [
  {
    tone: 'teal',
    title: 'Invoice to pay',
    desc: 'Every bill arrives in one queue and leaves as a payment you approved.',
    items: ['Capture from any channel', 'AI extraction', 'PO and GRN three-way match', 'Pay from your own bank'],
  },
  {
    tone: 'rust',
    title: 'Expenses',
    desc: 'Spending is claimed, checked against budget and settled without a spreadsheet.',
    items: ['Card feeds', 'Receipt capture', 'Mileage and per-diem', 'Claims against budget and advances'],
  },
  {
    tone: 'blue',
    title: 'Records',
    desc: 'One place for every document your finance team has to defend.',
    items: ['Encrypted vault', 'Version history', 'Retention and legal hold', 'Semantic search'],
  },
];

const problemCards = [
  {
    title: 'Invoices scatter',
    desc: 'Inboxes, WhatsApp, drive folders, a supervisor’s phone.',
    Icon: Inbox,
  },
  {
    title: 'People do work computers should do',
    desc: 'Download, code, re-key, chase.',
    Icon: Keyboard,
  },
  {
    title: 'Risk hides in the gaps',
    desc: 'A double payment. A vendor whose bank details changed last night.',
    Icon: AlertTriangle,
  },
  {
    title: 'The record never survives the audit',
    desc: 'The invoice, the approval and the payment live in three systems.',
    Icon: FolderOpen,
  },
];

const howSteps = [
  {
    code: '01',
    title: 'Capture',
    desc: 'It arrives by email, chat or phone.',
    meta: 'Any channel',
    Icon: Download,
  },
  {
    code: '02',
    title: 'Classify',
    desc: 'Invoice, receipt, statement or contract.',
    meta: 'Auto-typed',
    Icon: Tags,
  },
  {
    code: '03',
    title: 'Extract',
    desc: 'Every field read, every line item.',
    meta: 'OCR + AI',
    Icon: ScanText,
  },
  {
    code: '04',
    title: 'Match',
    desc: 'Against the order and the goods received.',
    meta: '3-way check',
    Icon: GitCompare,
  },
  {
    code: '05',
    title: 'Approve',
    desc: 'In your inbox or in your pocket.',
    meta: 'Policy routed',
    Icon: CheckCircle2,
  },
  {
    code: '06',
    title: 'Pay & post',
    desc: 'Your bank pays, your ledger updates.',
    meta: 'Same day',
    Icon: Banknote,
  },
];

const mobileHighlights = [
  { label: 'Three taps maximum', Icon: MousePointerClick },
  { label: 'Snap and submit', Icon: Camera },
  { label: 'Approvals with full context', Icon: ClipboardCheck },
  { label: 'Budget and advances in hand', Icon: Wallet },
];

const peopleCards = [
  {
    title: 'CFO',
    desc: 'Cash, exposure, and control assurance — signed off with confidence.',
    visual: 'cfo',
  },
  {
    title: 'Finance Manager',
    desc: 'Queues, exceptions, and close managed without spreadsheet chaos.',
    visual: 'finance',
  },
  {
    title: 'AP & accounts team',
    desc: 'No re-keying. Documents land ready for the next control gate.',
    visual: 'ap',
  },
  {
    title: 'Employees & field staff',
    desc: 'Snap a receipt, submit a claim, get paid — from the pocket.',
    visual: 'field',
  },
  {
    title: 'Auditors',
    desc: 'An evidence trail that holds: signed, timestamped, immutable.',
    visual: 'audit',
  },
];

function PeopleCardVisual({ visual }) {
  if (visual === 'cfo') {
    return (
      <div className="people-scene people-scene--cfo">
        <span className="people-avatar people-avatar--a">
          <User size={15} strokeWidth={2} />
        </span>
        <span className="people-avatar people-avatar--b">
          <User size={15} strokeWidth={2} />
        </span>
        <span className="people-avatar people-avatar--c">
          <Users size={14} strokeWidth={2} />
        </span>
      </div>
    );
  }

  if (visual === 'finance') {
    return (
      <div className="people-scene people-scene--finance">
        <div className="people-bars">
          <span />
          <span />
          <span />
          <span />
        </div>
        <span className="people-finance-mark">
          <DollarSign size={14} strokeWidth={2.25} />
        </span>
        <span className="people-finance-calc">
          <Calculator size={12} strokeWidth={2} />
        </span>
      </div>
    );
  }

  if (visual === 'ap') {
    return (
      <div className="people-scene people-scene--ap">
        <div className="people-sheet people-sheet--back" />
        <div className="people-sheet people-sheet--front">
          <span />
          <span />
          <span />
        </div>
        <span className="people-ap-mark">
          <FileSpreadsheet size={12} strokeWidth={2} />
        </span>
      </div>
    );
  }

  if (visual === 'field') {
    return (
      <div className="people-scene people-scene--field">
        <div className="people-phone">
          <span className="people-phone-notch" />
          <Camera size={13} strokeWidth={2} />
        </div>
        <div className="people-receipt">
          <span />
          <span />
          <span />
        </div>
      </div>
    );
  }

  return (
    <div className="people-scene people-scene--audit">
      <div className="people-checks">
        <span>
          <Check size={9} strokeWidth={2.5} />
        </span>
        <span>
          <Check size={9} strokeWidth={2.5} />
        </span>
        <span>
          <Check size={9} strokeWidth={2.5} />
        </span>
      </div>
      <span className="people-audit-mark">
        <SearchCheck size={14} strokeWidth={2} />
      </span>
    </div>
  );
}

const industryList = [
  {
    title: 'Aged care & NDIS providers',
    sub: '(claims, rostering, funding)',
    cta: 'Care',
    image: '/qll/industries/aged-care.png',
  },
  {
    title: 'Accounting & audit firms',
    sub: '(close, AP, assurance)',
    cta: 'Audit',
    image: '/qll/industries/accounting.png',
  },
  {
    title: 'Education & migration agencies',
    sub: '(enrolments, visas, fees)',
    cta: 'Learn',
    image: '/qll/industries/education.png',
  },
  {
    title: 'Logistics & freight',
    sub: '(POD, payables, fleet)',
    cta: 'Move',
    image: '/qll/industries/logistics.png',
  },
  {
    title: 'Construction & trades',
    sub: '(progress claims, job cost)',
    cta: 'Build',
    image: '/qll/industries/construction.png',
  },
  {
    title: 'Retail & DTC',
    sub: '(stock, suppliers, payouts)',
    cta: 'Sell',
    image: '/qll/industries/retail.png',
  },
  {
    title: 'Professional services',
    sub: '(WIP, retainers, bills)',
    cta: 'Advise',
    image: '/qll/industries/professional.png',
  },
  {
    title: 'Multi-entity groups',
    sub: '(group close, intercompany)',
    cta: 'Group',
    image: '/qll/industries/multi-entity.png',
  },
];

const presenceMapDots = [
  {
    start: { lat: 1.2868, lng: 103.8545, label: 'Singapore', side: 'singapore' },
    end: { lat: 39.1582, lng: -75.5244, label: 'USA' },
  },
  {
    start: { lat: 1.2868, lng: 103.8545 },
    end: { lat: -33.7766, lng: 151.1226, label: 'Australia', side: 'australia' },
  },
  {
    start: { lat: 1.2868, lng: 103.8545 },
    end: { lat: 20.5937, lng: 78.9629, label: 'India', side: 'left-above' },
  },
  {
    start: { lat: 1.2868, lng: 103.8545 },
    end: { lat: 16.8409, lng: 96.1735, label: 'Myanmar', side: 'myanmar' },
  },
];

const presenceOffices = [
  {
    city: 'USA',
    color: 'bg-[#2FD4B5]',
    name: 'High Volt Analytics L.L.C.',
    addr: '8 The Green STE B, Dover, DE 19901',
    contact: ['+1 585 361 5008', 'sales@highvolt.tech'],
  },
  {
    city: 'Australia',
    color: 'bg-[#2FD4B5]',
    name: 'High Volt Analytics Pty Ltd',
    addr: '2306A, 80 Waterloo, Macquarie Park, NSW 2113',
    contact: ['+61 410 503 579', 'sales@highvolt.tech'],
  },
  {
    city: 'Singapore',
    color: 'bg-[#2FD4B5]',
    name: 'High Volt Analytics Pte Ltd',
    addr: '68 Circular Road, #02-01, Singapore (049422)',
    contact: ['sales@highvolt.tech'],
  },
  {
    city: 'India',
    color: 'bg-[#2FD4B5]',
    name: 'High Volt Analytics',
    addr: 'O-HUB, Infocity Road, Bhubaneswar, Odisha 751024',
    contact: ['sales@highvolt.tech'],
  },
];

const pricingPlans = [
  {
    name: 'Free Plan',
    price: 'Free',
    priceNote: 'Every month',
    popular: false,
    cta: 'Get started',
    href: externalLinks.getStarted,
    features: [
      { label: 'Social media integration', included: false },
      { label: 'Email integration', included: false },
      { label: 'Upload', included: true },
    ],
  },
  {
    name: 'Company',
    price: 'US$150',
    priceNote: '/ month, per company',
    popular: true,
    cta: 'Get it now',
    href: externalLinks.getStarted,
    features: [
      { label: 'Additional pages — US$0.25 each, any size', included: true },
      { label: 'Additional users — US$10 per user, per month', included: true },
      { label: 'Implementation — US$0. Live in 7 days.', included: true },
      { label: 'No lock-in. Cancel any time.', included: true },
    ],
  },
];

function PricingCard({ plan }) {
  const includedFeatures = plan.features.filter((feature) => feature.included);
  const excludedFeatures = plan.features.filter((feature) => !feature.included);
  const orderedFeatures = [...includedFeatures, ...excludedFeatures];

  return (
    <div className={`pricing-card ${plan.popular ? 'pricing-card--popular' : ''}`}>
      {plan.popular && <span className="pricing-card-badge">Most popular</span>}

      <h3 className="text-base font-semibold text-foreground">{plan.name}</h3>

      <div className="mt-6 flex items-end gap-1.5">
        <span className="text-4xl font-semibold tracking-tight text-foreground">{plan.price}</span>
        {plan.priceNote && (
          <span className="mb-1 text-sm text-muted-foreground">{plan.priceNote}</span>
        )}
      </div>

      <div className="pricing-card-divider my-6" />

      <ul className="flex flex-1 flex-col gap-3">
        {orderedFeatures.map((feature) => (
          <li key={feature.label} className="flex items-start gap-2.5 text-sm text-muted-foreground">
            <span className={`pricing-check ${feature.included ? '' : 'pricing-check--excluded'}`}>
              {feature.included ? (
                <Check className="h-3 w-3" strokeWidth={3} />
              ) : (
                <X className="h-3 w-3" strokeWidth={3} />
              )}
            </span>
            <span>{feature.label}</span>
          </li>
        ))}
      </ul>

      <a
        href={plan.href}
        target="_blank"
        rel="noopener noreferrer"
        className={`pricing-card-cta mt-8 w-full ${plan.popular ? 'pricing-card-cta--popular' : ''}`}
      >
        {plan.cta}
      </a>
    </div>
  );
}

export default function QuantumLedgerLinkPage() {
  const [videoPlaying, setVideoPlaying] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    document.body.classList.add('qll-page');
    return () => document.body.classList.remove('qll-page');
  }, []);

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const root = rootRef.current;
    if (!root) return;

    const revealables = root.querySelectorAll('.r');
    if (reduce || !('IntersectionObserver' in window)) {
      document.body.classList.add('no-motion');
      revealables.forEach((el) => el.classList.add('in'));
      return undefined;
    }

    const ro = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('in');
            ro.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
    );

    revealables.forEach((el, i) => {
      el.style.transitionDelay = `${Math.min(i % 6, 4) * 45}ms`;
      ro.observe(el);
    });

    return () => ro.disconnect();
  }, []);

  return (
    <div className="qll-site" ref={rootRef}>
      <a className="skip" href="#hero">
        Skip to content
      </a>

      <Header />

      <main>
        <section className="s dark hero" id="hero">
          <div className="grid-bg" aria-hidden="true" />
          <div className="glow" aria-hidden="true" />
          <div className="wrap">
            <div className="hero-copy">
              <p className="eyebrow r">Invoice to pay · Expenses · Records</p>
              <h1 className="h1 r">Every dollar that leaves your business, back in your hands.</h1>
              <p className="lead r">
                Quantum Ledgerline captures the document, runs the controls, pays from your own bank, and
                files the record. One system, from the invoice to the audit.
              </p>
              <div className="actions r in">
                <a
                  className="btn btn-primary"
                  href={externalLinks.getStarted}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ background: '#2FD4B5', color: '#04161C' }}
                >
                  Start free
                </a>
                <a
                  className="btn btn-ghost"
                  href="#video"
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById('video')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  }}
                >
                  Watch the product video
                </a>
              </div>
            </div>

            <div className="hero-video" id="video">
              <div className="video r" id="videoWrap">
                {videoPlaying ? (
                  <iframe
                    src={YOUTUBE_EMBED}
                    title="Quantum Ledgerline — the whole product in two minutes"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowFullScreen
                    referrerPolicy="strict-origin-when-cross-origin"
                  />
                ) : (
                  <button
                    className="video-btn"
                    type="button"
                    aria-label="Play the Quantum Ledgerline product video"
                    onClick={() => setVideoPlaying(true)}
                  >
                    <img
                      src="/qll/video-poster.jpg"
                      alt="A finance team member working at a desk with Quantum Ledgerline open on a laptop."
                      width="1280"
                      height="720"
                      loading="lazy"
                      decoding="async"
                    />
                    <span className="play" aria-hidden="true">
                      <svg viewBox="0 0 64 64" fill="none">
                        <circle cx="32" cy="32" r="31.25" stroke="#fff" strokeWidth="1.5" />
                        <path d="M26 22.5 43 32l-17 9.5V22.5Z" fill="#fff" />
                      </svg>
                    </span>
                  </button>
                )}
              </div>
            </div>

            <div className="hero-meta">
              <p className="strip r">
                Captures via email · WhatsApp · Viber · mobile <span className="sep">·</span> Pays from your
                bank <span className="sep">·</span> Posts to Xero · QuickBooks · MYOB · NetSuite
              </p>
              <ul className="figs r">
                <li>
                  <span className="fig">3 seconds</span>
                  <span className="figlabel">per invoice</span>
                </li>
                <li>
                  <span className="fig">12</span>
                  <span className="figlabel">control gates</span>
                </li>
                <li>
                  <span className="fig">Δ$0.00</span>
                  <span className="figlabel">daily reconciliation</span>
                </li>
              </ul>
            </div>
          </div>
        </section>

        <section className="s paper" id="problem">
          <div className="wrap">
            <p className="eyebrow r">The problem</p>
            <h2 className="h2 r">Right now, nobody can tell you what you owe.</h2>
            <p className="lead r">
              15 minutes and about <span className="num">US$30</span> of somebody&apos;s time, per invoice.
            </p>

            <div className="problem-grid r">
              {problemCards.map(({ title, desc, Icon }) => (
                <article key={title} className="problem-card">
                  <Icon className="problem-icon" strokeWidth={2} aria-hidden="true" />
                  <h3 className="problem-card-title">{title}</h3>
                  <p className="problem-card-desc">{desc}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="s dark ink2" id="product">
          <div className="wrap">
            <p className="eyebrow r">Three in one</p>
            <h2 className="h2 r">Three systems your team stopped needing.</h2>
            <div className="product-glow-grid r">
              {productCards.map(({ tone, title, desc, items }) => (
                <article key={title} className={`product-glow-card product-glow-card--${tone}`}>
                  <h3>{title}</h3>
                  <p>{desc}</p>
                  <ul>
                    {items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
            <p className="closer r">One pipeline. One audit trail. One place to look.</p>
          </div>
        </section>

        <section className="s dark" id="how">
          <div className="wrap">
            <p className="eyebrow r">How it works</p>
            <h2 className="h2 wide r">One document lands. Twelve checks run. You approve. It pays.</h2>
            <div className="how-grid r">
              {howSteps.map(({ code, title, desc, meta, Icon }) => (
                <article key={code} className="capture-ref-card how-card group flex h-full flex-col">
                  <div className="capture-ref-body how-card-body flex h-full flex-col">
                    <div className="flex items-center justify-between gap-2">
                      <div className="capture-brand-logo">
                        <Icon className="h-3.5 w-3.5 text-[#2FD4B5]" strokeWidth={2} aria-hidden="true" />
                      </div>
                      <span className="font-mono text-[10px] font-medium text-muted-foreground">{code}</span>
                    </div>
                    <h3 className="how-card-title">{title}</h3>
                    <p className="how-card-desc">{desc}</p>
                    <p className="capture-channel-meta how-card-meta">{meta}</p>
                  </div>
                </article>
              ))}
            </div>
            <div className="band r">
              <div className="bandcol">
                <p className="bandlabel">Before</p>
                <p className="bandfig">
                  <span className="num">15 minutes</span>
                </p>
                <p className="bandsub">
                  <span className="num">US$30</span> per invoice
                </p>
              </div>
              <div className="bandcol">
                <p className="bandlabel">With Ledgerline</p>
                <p className="bandfig accent">
                  <span className="num">3 seconds</span>
                </p>
                <p className="bandsub">
                  <span className="num">US$3</span> per invoice
                </p>
              </div>
            </div>
            <p className="statline r">
              AI reads the document. Deterministic rules do the accounting. That separation is why auditors trust it.
            </p>
          </div>
        </section>

        <section className="s dark ink2" id="controls">
          <div className="wrap">
            <p className="eyebrow r">CFO-grade controls</p>
            <h2 className="h2 r">Six gates between the invoice and the wire.</h2>
            <p className="lead r">
              Every control is enforced server-side. The UI may hint; the API rejects. This is the layer
              CFOs trust enough to sign for.
            </p>
            <div className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {controls.map((ctrl) => {
                const Icon = controlIcons[ctrl.code];
                return (
                  <article key={ctrl.code} className="control-glass-card group relative flex h-full flex-col p-6 r">
                    <div className="relative z-10 flex h-full flex-col">
                      <div className="flex items-center justify-between gap-3">
                        <div className="control-icon-box">
                          <Icon className="control-icon-symbol h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
                        </div>
                        <span className="font-mono text-[11px] font-medium text-muted-foreground">{ctrl.code}</span>
                      </div>
                      <h3 className="mt-5 text-lg font-medium tracking-[-0.02em] text-foreground">{ctrl.title}</h3>
                      <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">{ctrl.desc}</p>
                      <p className="control-blocks-badge mt-4 whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.14em]">
                        {ctrl.blocks}
                      </p>
                    </div>
                  </article>
                );
              })}
            </div>
            <p className="closer r">
              Enforced server-side. The interface may hint; the API refuses. Funds never leave your bank —
              we instruct, your bank executes.
            </p>
          </div>
        </section>

        <section className="s paper" id="mobile">
          <div className="wrap">
            <p className="eyebrow r">Mobile</p>
            <h2 className="h2 r">Approve from your pocket. Capture from the field.</h2>
            <div className="phones r">
              <figure className="phone">
                <div className="frame">
                  <img
                    src="/qll/app-home.png"
                    alt="Quantum Ledgerline mobile home screen showing quarter budget, advance outstanding and recent activity."
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <figcaption>Your quarter, at a glance</figcaption>
              </figure>
              <figure className="phone">
                <div className="frame">
                  <img
                    src="/qll/app-capture.png"
                    alt="Quantum Ledgerline capture review screen showing an extracted receipt ready to submit."
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <figcaption>Snap, review, submit</figcaption>
              </figure>
              <figure className="phone">
                <div className="frame">
                  <img
                    src="/qll/app-approvals.png"
                    alt="Quantum Ledgerline approvals inbox listing claims awaiting a decision."
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <figcaption>Approvals with context</figcaption>
              </figure>
            </div>
            <div className="mobile-highlights r in" role="list">
              {mobileHighlights.map(({ label, Icon }, i) => (
                <div key={label} className="mobile-highlight" role="listitem">
                  {i > 0 ? <span className="mobile-highlight-dot" aria-hidden="true" /> : null}
                  <Icon size={14} strokeWidth={2.25} className="mobile-highlight-icon" aria-hidden="true" />
                  <span className="mobile-highlight-label">{label}</span>
                </div>
              ))}
            </div>
            <p className="tag r">Shipping soon · included in the platform</p>
          </div>
        </section>

        <IntegrationsSection />

        <section className="s dark ink2" id="audience">
          <div className="wrap">
            <p className="eyebrow r">Who it&apos;s for</p>
            <h2 className="h2 r">Built for the people who sign, and the people who spend.</h2>

            <h3 className="blabel audience-sublabel r">People</h3>
            <div className="people-grid r">
              {peopleCards.map(({ title, desc, visual }) => (
                <article key={title} className="people-card">
                  <div className={`people-card-visual people-card-visual--${visual}`} aria-hidden="true">
                    <PeopleCardVisual visual={visual} />
                  </div>
                  <h4 className="people-card-title">{title}</h4>
                  <p className="people-card-desc">{desc}</p>
                </article>
              ))}
            </div>

            <h3 className="blabel industry-heading r">Industries</h3>
          </div>
          <div className="industry-marquee r">
            <div className="industry-track">
              {[...industryList, ...industryList].map((item, i) => (
                <article key={`${item.title}-${i}`} className="industry-badge">
                  <img src={item.image} alt={item.title} />
                  <div className="industry-badge-copy">
                    <p className="industry-badge-title">{item.title}</p>
                    <p className="industry-badge-sub">{item.sub}</p>
                  </div>
                  <span className="industry-badge-cta">{item.cta}</span>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="s paper" id="team">
          <div className="wrap">
            <p className="eyebrow r">Why us</p>
            <h2 className="h2 r">Founder-led. Globally distributed.</h2>
            <p className="lead r">
              A team of IITians, Chartered Accountants and industry process-automation experts. Startup
              velocity, with enterprise rigour.
            </p>
            <div className="actions r">
              <a
                className="btn btn-primary"
                href={externalLinks.website}
                target="_blank"
                rel="noopener noreferrer"
              >
                Website
              </a>
            </div>
          </div>
        </section>

        <section className="s dark" id="presence">
          <div className="wrap">
            <p className="eyebrow r">Presence</p>
            <h2 className="h2 r">Four offices. One team. Your business hours.</h2>
            <p className="lead r">Connect with us across continents globally.</p>

            <div className="presence-map r">
              <WorldMap dots={presenceMapDots} lineColor="#2FD4B5" />

              <div className="presence-offices">
                {presenceOffices.map((loc) => (
                  <div key={loc.city} className="presence-office">
                    <div className="presence-office-city">
                      <span className={`presence-dot ${loc.color}`} />
                      <h3>{loc.city}</h3>
                    </div>
                    <p className="presence-office-name">{loc.name}</p>
                    <p className="presence-office-addr">{loc.addr}</p>
                    <div className="presence-office-contact">
                      {loc.contact.map((info) => (
                        <p key={info}>{info}</p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="s paper" id="pricing">
          <div className="wrap">
            <p className="eyebrow r">Commercial</p>
            <h2 className="h2 r">Simple, honest pricing.</h2>
            <p className="lead r">Start free, upgrade when you need more pages, access, and integrations.</p>

            <div className="qll-pricing-grid r">
              {pricingPlans.map((plan) => (
                <PricingCard key={plan.name} plan={plan} />
              ))}
            </div>
          </div>
        </section>

        <section className="s dark ink2 close" id="close">
          <div className="wrap">
            <p className="eyebrow r">Next step</p>
            <h2 className="h2 r">See it run on your own invoices.</h2>
            <p className="lead r">
              Book a 20-minute call. We run your volume through the model and give you a written
              implementation plan.
            </p>
            <div className="actions r">
              <a
                className="btn btn-primary"
                href={externalLinks.getStarted}
                target="_blank"
                rel="noopener noreferrer"
                style={{ background: '#2FD4B5', color: '#04161C' }}
              >
                Start free
              </a>
              <a className="btn btn-ghost" href="mailto:sales@highvolt.tech">
                Talk to us
              </a>
            </div>
            <p className="contacts r">
              <a href="mailto:sana@highvolt.tech">sana@highvolt.tech</a>
              <span className="sep">·</span>
              <a href="mailto:sithu@highvolt.tech">sithu@highvolt.tech</a>
              <span className="sep">·</span>
              <a href="mailto:sales@highvolt.tech">sales@highvolt.tech</a>
            </p>
          </div>
        </section>
      </main>

      <footer className="foot dark">
        <div className="wrap footin">
          <span className="fbrand">
            <Logo className="h-7 sm:h-8" />
            High Volt Analytics
          </span>
          <span className="flinks">
            <a href="https://quantumledgerlink.com" target="_blank" rel="noopener noreferrer">
              quantumledgerlink.com
            </a>
            <a href="https://highvolt.tech" target="_blank" rel="noopener noreferrer">
              highvolt.tech
            </a>
          </span>
          <span className="fcities">Sydney · Singapore · India · USA</span>
        </div>
      </footer>
    </div>
  );
}
