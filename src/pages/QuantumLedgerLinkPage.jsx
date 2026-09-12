import { useEffect, useRef, useState, Fragment } from 'react';
import {
  Users,
  Keyboard,
  AlertTriangle,
  FolderOpen,
  FileText,
  Files,
  RefreshCw,
  Clock,
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
  TrendingUp,
  ChevronRight,
  Zap,
} from 'lucide-react';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';
import HowVisual from '../components/ui/HowVisuals';
import { WorldMap } from '../components/ui/WorldMap';
import IntegrationsSection from '../components/sections/IntegrationsSection';
import { externalLinks } from '../data/navigation';
import '../qll.css';

const YOUTUBE_EMBED =
  'https://www.youtube-nocookie.com/embed/0luxUk3VtgA?autoplay=1&rel=0&modestbranding=1';

const compareRows = [
  {
    today: 'Documents scattered everywhere',
    ledger: 'Captured automatically from authorised channels',
    Icon: FileText,
  },
  {
    today: 'Manual data entry',
    ledger: 'AI reads & understands the document',
    Icon: Keyboard,
  },
  {
    today: 'Manual classification & filing',
    ledger: 'Automatically classified & stored',
    Icon: FolderOpen,
  },
  {
    today: 'Approvals chased manually',
    ledger: 'Approvals intelligently routed',
    Icon: RefreshCw,
  },
  {
    today: 'Duplicates & errors found late',
    ledger: 'Exceptions detected before processing',
    Icon: AlertTriangle,
  },
  {
    today: 'Payment disconnected from workflow',
    ledger: 'Invoice → approval → payment connected',
    Icon: Banknote,
  },
  {
    today: 'Records spread across systems',
    ledger: 'Complete audit-ready record maintained',
    Icon: Files,
  },
  {
    today: 'Finance spends time processing',
    ledger: 'Finance focuses on decisions & exceptions',
    Icon: Clock,
  },
];

const howFlows = [
  {
    title: 'Invoice to Pay',
    subtitle: 'Simple. Automated. Controlled.',
    stages: [
      {
        name: '1. Capture & Understand',
        tone: 'blue',
        steps: [
          {
            n: '1',
            title: 'Capture Invoices',
            desc: 'Invoices arrive from WhatsApp, Viber, email, app, or Slack.',
            visual: 'capture',
          },
          {
            n: '2',
            title: 'Analyse Document',
            desc: 'AI reads each file and analyses the document instantly.',
            visual: 'analyse',
          },
          {
            n: '3',
            title: 'Classify Type',
            desc: 'Identifies invoice, receipt, statement, or supporting file.',
            visual: 'classify',
          },
          {
            n: '4',
            title: 'Extract & Attach',
            desc: 'Extracts key details and links supporting documents automatically.',
            visual: 'extract',
          },
        ],
      },
      {
        name: '2. Check, Post & Store',
        tone: 'teal',
        steps: [
          {
            n: '5',
            title: 'Apply Rules',
            desc: 'Finds the right rulebook or policy for the document.',
            visual: 'rules',
          },
          {
            n: '6',
            title: 'Check Budget & Approval',
            desc: 'Checks budget, advance, and approval matrix.',
            visual: 'budget',
          },
          {
            n: '7',
            title: 'Suggest Coding',
            desc: 'Suggests description, ledger, and sub-ledger mapping.',
            visual: 'coding',
          },
          {
            n: '8',
            title: 'Validate & Create Entry',
            desc: 'Checks invoice number, due date, and tax, then creates the entry.',
            visual: 'validate',
          },
          {
            n: '9',
            title: 'Sync to Accounting',
            desc: 'Syncs to the accounting system and keeps it in draft stage.',
            visual: 'sync',
          },
          {
            n: '10',
            title: 'Archive & Store',
            desc: 'Auto-attaches supporting documents and stores everything in the right folder.',
            visual: 'archive',
          },
        ],
      },
    ],
  },
  {
    title: 'Expense Management',
    subtitle: 'Simple. Automated. Fast.',
    foot: 'All in 2 seconds — from request to payment, fully automated.',
    stages: [
      {
        name: '1. Advance Request',
        tone: 'blue',
        steps: [
          {
            n: '1',
            title: 'Raise Request',
            desc: 'Field staff, sales or any team raises an advance request.',
            visual: 'raise',
          },
          {
            n: '2',
            title: 'Supervisor Approval',
            desc: 'Routed to supervisor for authorization.',
            visual: 'supervisor',
          },
          {
            n: '3',
            title: 'Finance Approval',
            desc: 'Routed to finance for approval.',
            visual: 'finance',
          },
          {
            n: '4',
            title: 'Funds Credited',
            desc: 'Funds credited to staff account in 1 minute.',
            visual: 'funds',
          },
        ],
      },
      {
        name: '2. Expense Claim',
        tone: 'teal',
        steps: [
          {
            n: '1',
            title: 'Upload Invoice',
            desc: 'Team takes a photo of the invoice and uploads it.',
            visual: 'upload',
          },
          {
            n: '2',
            title: 'Automated Checks',
            desc: 'System checks against advance, budget, and policy.',
            visual: 'checks',
          },
          {
            n: '3',
            title: 'Routed for Approval',
            desc: 'Routed based on the approval matrix.',
            visual: 'routed',
          },
          {
            n: '4',
            title: 'Payment Released',
            desc: 'Approved amount is released.',
            visual: 'payment',
          },
        ],
      },
    ],
  },
  {
    title: 'File Management',
    subtitle: 'Capture. Organize. Bundle. Notify.',
    foot: 'From file capture to bundled reporting — fast, organized, and automated.',
    stages: [
      {
        name: '1. Capture & Organize',
        tone: 'blue',
        steps: [
          {
            n: '1',
            title: 'Capture Files',
            desc: 'Files arrive from email, WhatsApp, Slack, Viber, app, or other channels.',
            visual: 'captureFiles',
          },
          {
            n: '2',
            title: 'Route to Folder',
            desc: 'Each file lands automatically in the correct folder.',
            visual: 'routeFolder',
          },
          {
            n: '3',
            title: 'Time-Stamp & Index',
            desc: 'Tagged by vendor, year, month, date, and timestamp.',
            visual: 'timestamp',
          },
          {
            n: '4',
            title: 'Organize Structure',
            desc: 'Files are arranged in a searchable, structured archive.',
            visual: 'organize',
          },
        ],
      },
      {
        name: '2. Match, Bundle & Notify',
        tone: 'teal',
        steps: [
          {
            n: '5',
            title: 'Find Companion Files',
            desc: 'The system searches for related or supporting documents.',
            visual: 'companion',
          },
          {
            n: '6',
            title: 'Auto-Bundle',
            desc: 'When a supporting file arrives, it is linked and bundled automatically.',
            visual: 'bundle',
          },
          {
            n: '7',
            title: 'Update Records',
            desc: 'The file set updates instantly with the latest attachments and status.',
            visual: 'update',
          },
          {
            n: '8',
            title: 'Report & Notify',
            desc: 'Reports are updated and notifications are sent automatically.',
            visual: 'report',
          },
        ],
      },
    ],
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

function HowStep({ n, title, desc, visual }) {
  return (
    <li className="how-step">
      <HowVisual name={visual} />
      <p className="how-step-title">
        {n}. {title}
      </p>
      <p className="how-step-desc">{desc}</p>
    </li>
  );
}

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
  const [howTab, setHowTab] = useState(0);
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
              <h1 className="h1 r">Every invoice. Every expense. Every record. Handled.</h1>
              <p className="lead r">
                One intelligent system that runs finance work from capture to payment to audit.
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
            </div>
          </div>
        </section>

        <div id="product" className="product-block">
        <section className="s dark tight compare-section" id="problem">
          <div className="wrap">
            <p className="eyebrow r">Today versus Ledgerline</p>
            <h2 className="h2 r">Right now, nobody can tell you what you owe.</h2>

            <div className="compare-board r">
              <span className="compare-orb compare-orb--warm" aria-hidden="true" />
              <span className="compare-orb compare-orb--cool" aria-hidden="true" />

              <p className="compare-title compare-title--today">Today</p>
              <span className="compare-title-spacer" aria-hidden="true" />
              <p className="compare-title compare-title--ledger">With Ledgerline</p>

              <article className="compare-card compare-card--today">
                {compareRows.map(({ today }) => (
                  <p className="compare-row" key={today}>
                    {today}
                  </p>
                ))}
              </article>

              <div className="compare-rail" aria-hidden="true">
                {compareRows.map(({ today, Icon }) => (
                  <span className="compare-rail-item" key={today}>
                    <Icon strokeWidth={1.75} />
                  </span>
                ))}
              </div>

              <article className="compare-card compare-card--ledger">
                {compareRows.map(({ today, ledger }) => (
                  <p className="compare-row" key={today}>
                    {ledger}
                  </p>
                ))}
              </article>
            </div>
          </div>
        </section>

        <section className="s dark ink2 outcome-section">
          <div className="wrap">
            <p className="outcome-kicker r">
              <span className="outcome-kicker-dot" aria-hidden="true" />
              The outcome
            </p>
            <h2 className="outcome-heading r">
              Finance runs itself.
              <br />
              Your people move forward.
            </h2>
            <p className="outcome-lead r">
              98% less processing time. 99% accuracy. 24/7 automation. 40%+ cost savings.*
            </p>

            <div className="outcome-bento r">
              <article className="outcome-card outcome-card--247">
                <h3>24/7 Always Running</h3>
                <p>Invoices. Expenses. Records.</p>
              </article>

              <article className="outcome-card outcome-card--time">
                <p>Seconds, not minutes.</p>
                <div className="outcome-metric">
                  <p className="outcome-num">
                    98<span>%</span>
                  </p>
                  <p className="outcome-label">Time Saved</p>
                </div>
              </article>

              <article className="outcome-card outcome-card--accuracy">
                <h3>99% Accuracy</h3>
                <p>Duplicates and suspicious invoices flagged.</p>
              </article>

              <article className="outcome-card outcome-card--cost">
                <p className="outcome-num">
                  40%<span>+</span>
                </p>
                <p className="outcome-label">Cost Saved*</p>
              </article>

              <article className="outcome-card outcome-card--pill">
                <span className="outcome-pill-dot" aria-hidden="true" />
                Guaranteed efficiency.
              </article>

              <article className="outcome-card outcome-card--faster">
                <TrendingUp className="outcome-watermark" strokeWidth={1.25} aria-hidden="true" />
                <h3>And the business moves faster.</h3>
                <ul>
                  <li>
                    <strong>Faster reporting</strong>
                    <span>Books stay current.</span>
                  </li>
                  <li>
                    <strong>Better cash visibility</strong>
                    <span>Know what&apos;s due and what&apos;s coming.</span>
                  </li>
                  <li>
                    <strong>Audit ready</strong>
                    <span>Every document. Every approval. Every record.</span>
                  </li>
                </ul>
                <p className="outcome-faster-foot">People do what people do best. Think. Decide. Grow.</p>
              </article>
            </div>
          </div>
        </section>
        </div>

        <section className="s dark" id="how">
          <div className="wrap">
            <p className="eyebrow r">How it works</p>
            <h2 className="h2 wide r">Simple. Automated. Controlled.</h2>

            <div className="how-tabs r" role="tablist" aria-label="How it works">
              {howFlows.map((flow, index) => (
                <button
                  key={flow.title}
                  type="button"
                  role="tab"
                  aria-selected={howTab === index}
                  className={`how-tab${howTab === index ? ' is-active' : ''}`}
                  onClick={() => setHowTab(index)}
                >
                  {flow.title}
                </button>
              ))}
            </div>

            {howFlows.map((flow, index) => (
              <article
                key={flow.title}
                className="how-board r"
                role="tabpanel"
                hidden={howTab !== index}
              >
                <header className="how-board-head">
                  <h3>{flow.title} – How It Works</h3>
                  <p>{flow.subtitle}</p>
                </header>

                {flow.stages.map((stage) => (
                  <div key={stage.name} className={`how-stage how-stage--${stage.tone}`}>
                    <p className="how-stage-label">{stage.name}</p>
                    <ol className={`how-flow how-flow--${stage.steps.length}`}>
                      {stage.steps.map((step, stepIndex) => (
                        <Fragment key={step.title}>
                          {stepIndex > 0 ? (
                            <li className="how-flow-arrow" aria-hidden="true">
                              <ChevronRight strokeWidth={2} />
                            </li>
                          ) : null}
                          <HowStep {...step} />
                        </Fragment>
                      ))}
                    </ol>
                  </div>
                ))}

                {flow.foot ? (
                  <p className="how-board-foot">
                    <Zap className="how-board-foot-icon" strokeWidth={2} aria-hidden="true" />
                    {flow.foot}
                  </p>
                ) : null}
              </article>
            ))}
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
