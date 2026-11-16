import { useEffect, useRef, useState, Fragment } from 'react';
import { Link } from 'react-router-dom';
import {
  MousePointerClick,
  Camera,
  ClipboardCheck,
  Wallet,
  Receipt,
  CircleCheck,
  ThumbsUp,
  ThumbsDown,
  Copy,
  SearchCheck,
  Check,
  ChevronRight,
  Zap,
  CalendarCheck,
  Send,
} from 'lucide-react';
import Header from '../components/layout/Header';
import SiteFooter from '../components/layout/SiteFooter';
import GradientCard from '../components/ui/GradientCard';
import HowVisual from '../components/ui/HowVisuals';
import { WorldMap } from '../components/ui/WorldMap';
import IntegrationsSection from '../components/sections/IntegrationsSection';
import ProblemSolutionSection from '../components/sections/ProblemSolutionSection';
import { bookDemoPath, externalLinks } from '../data/navigation';
import '../qll.css';

const YOUTUBE_EMBED =
  'https://www.youtube-nocookie.com/embed/SElwFjDrqLI?autoplay=1&rel=0&modestbranding=1';
const TEAM_YOUTUBE_EMBED =
  'https://www.youtube-nocookie.com/embed/5Xw_KPwWrR8?autoplay=1&rel=0&modestbranding=1';
const INVOICE_YOUTUBE_EMBED =
  'https://www.youtube-nocookie.com/embed/XZUaMXvXw-w?autoplay=1&rel=0&modestbranding=1';

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
    title: 'Invoice to Cash',
    subtitle: 'Bill. Collect. Reconcile.',
    stages: [
      {
        name: '1. Capture & Bill',
        tone: 'blue',
        steps: [
          {
            n: '1',
            title: 'Capture Billing Docs',
            desc: 'Invoices, contracts, and delivery notes arrive from email, WhatsApp, or Slack.',
            visual: 'capture',
          },
          {
            n: '2',
            title: 'Analyse Document',
            desc: 'AI reads the file and pulls the customer, amount, tax, and due date.',
            visual: 'analyse',
          },
          {
            n: '3',
            title: 'Match the Customer',
            desc: 'Links the document to the right customer, order, or contract.',
            visual: 'classify',
          },
          {
            n: '4',
            title: 'Raise the Receivable',
            desc: 'Creates the invoice and the accounting entry, ready to send.',
            visual: 'extract',
          },
        ],
      },
      {
        name: '2. Collect & Post',
        tone: 'teal',
        steps: [
          {
            n: '5',
            title: 'Send for Collection',
            desc: 'The invoice goes out and the balance is tracked until it is paid.',
            visual: 'rules',
          },
          {
            n: '6',
            title: 'Record the Payment',
            desc: 'Incoming payment is matched to the open invoice.',
            visual: 'payment',
          },
          {
            n: '7',
            title: 'Sync to Accounting',
            desc: 'The receipt and the cleared invoice post to the accounting system.',
            visual: 'sync',
          },
          {
            n: '8',
            title: 'Archive & Store',
            desc: 'The invoice, proof of delivery, and receipt are filed together.',
            visual: 'archive',
          },
        ],
      },
    ],
  },
  {
    title: 'Team Expenses Mgt',
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
    title: 'Document Mgt',
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
        <svg className="cfo-trend" viewBox="0 0 240 90" aria-hidden="true">
          <defs>
            <linearGradient id="cfo-trend-glow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2FD4B5" stopOpacity="0.28" />
              <stop offset="100%" stopColor="#2FD4B5" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path
            d="M0 62 C40 60 70 52 100 54 C130 56 150 48 175 50 C200 52 220 48 240 50 L240 90 L0 90 Z"
            fill="url(#cfo-trend-glow)"
          />
          <path
            className="cfo-trend-line"
            d="M0 62 C40 60 70 52 100 54 C130 56 150 48 175 50 C200 52 220 48 240 50"
          />
          <circle cx="175" cy="50" r="3.2" fill="#0C1620" stroke="#2FD4B5" strokeWidth="1.6" />
        </svg>

        <span className="cfo-float cfo-plane">
          <Send size={14} strokeWidth={2.4} />
        </span>
        <span className="cfo-float cfo-bolt">
          <Zap size={18} strokeWidth={2.2} />
        </span>
        <span className="cfo-float cfo-pie" aria-hidden="true">
          <svg viewBox="0 0 32 32">
            <circle cx="16" cy="16" r="13" fill="#12202A" />
            <path d="M16 16 L16 3.5 A12.5 12.5 0 0 1 27.2 21.2 Z" fill="#2FD4B5" />
            <path d="M16 16 L27.2 21.2 A12.5 12.5 0 0 1 7.2 24.4 Z" fill="#1A8F7A" />
          </svg>
        </span>

        <div className="cfo-pill">
          <span className="cfo-orb cfo-orb--cal">
            <CalendarCheck size={16} strokeWidth={2.2} />
          </span>
          <span className="cfo-orb cfo-orb--face">
            <img src="/qll/cfo-user-a.png" alt="" />
          </span>
          <span className="cfo-orb cfo-orb--face">
            <img src="/qll/cfo-user-b.png" alt="" />
          </span>
          <span className="cfo-orb cfo-orb--plus">+2</span>
        </div>
      </div>
    );
  }

  if (visual === 'finance') {
    return (
      <div className="people-scene people-scene--finance">
        <svg className="fin-multi" viewBox="0 0 240 140" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
          <text className="fin-axis" x="2" y="20">100</text>
          <text className="fin-axis" x="6" y="72">50</text>
          <text className="fin-axis" x="10" y="126">0</text>
          <path className="fin-series fin-series--soft" d="M32 40 C80 38 120 28 168 24" />
          <path className="fin-series" d="M32 96 C62 94 82 80 92 74 C102 68 138 56 168 52" />
          <path className="fin-series fin-series--muted" d="M32 114 C90 112 130 108 168 106" />
          <line x1="92" y1="12" x2="92" y2="128" className="fin-guide" />
          <circle cx="92" cy="74" r="3.6" className="fin-node" />
          <g className="fin-tip">
            <rect x="61" y="48" width="62" height="16" rx="8" />
            <text x="92" y="59" textAnchor="middle">37 <tspan className="fin-tip-up">+1.2%</tspan></text>
          </g>
          <g className="fin-pill fin-pill--cash">
            <rect x="178" y="16" width="52" height="16" rx="8" />
            <text x="204" y="27" textAnchor="middle">Cash</text>
          </g>
          <g className="fin-pill fin-pill--close">
            <rect x="178" y="44" width="52" height="16" rx="8" />
            <text x="204" y="55" textAnchor="middle">Close</text>
          </g>
          <g className="fin-pill fin-pill--queue">
            <rect x="178" y="98" width="52" height="16" rx="8" />
            <text x="204" y="109" textAnchor="middle">Queue</text>
          </g>
        </svg>
      </div>
    );
  }

  if (visual === 'ap') {
    return (
      <div className="people-scene people-scene--ap">
        <div className="acct-board">
          <p>Invoice checked. Ready for the next control gate.</p>
          <span className="acct-k">Title</span>
          <span className="acct-bar" />
          <span className="acct-k">Content</span>
          <span className="acct-bar acct-bar--mid" />
          <div className="acct-row">
            <span><ThumbsUp size={10} strokeWidth={2.2} /> Like</span>
            <span><ThumbsDown size={10} strokeWidth={2.2} /> Dislike</span>
          </div>
        </div>
        <div className="acct-pop">
          <span><ThumbsUp size={10} strokeWidth={2.2} /> Like</span>
          <span><ThumbsDown size={10} strokeWidth={2.2} /> Dislike</span>
          <span><Copy size={10} strokeWidth={2.2} /> Copy</span>
        </div>
      </div>
    );
  }

  if (visual === 'field') {
    return (
      <div className="people-scene people-scene--field">
        <div className="inv-panel">
          <div className="inv-card inv-card--back" />
          <div className="inv-card inv-card--mid">
            <span className="inv-ico"><Receipt size={11} strokeWidth={2} /></span>
            <span className="inv-name">Invoice #25</span>
            <CircleCheck size={14} className="inv-ok" strokeWidth={2} />
          </div>
          <div className="inv-card inv-card--front">
            <span className="inv-ico"><Receipt size={11} strokeWidth={2} /></span>
            <span className="inv-copy">
              <strong>Invoice #27</strong>
              <em>+ $2,450.00</em>
            </span>
            <CircleCheck size={14} className="inv-ok" strokeWidth={2} />
          </div>
          <span className="inv-create">Create +</span>
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

const industryCards = [
  {
    tone: 'teal',
    badgeText: 'Case study',
    badgeColor: '#5EEAD4',
    title: 'Spectra',
    description:
      'Export and import across countries. Scattered trade documents become an audit-ready ledger posting.',
    ctaText: 'Read the story',
    href: '/industries/spectra',
    imageUrl: '/qll/industries/spectra-hero.jpg',
  },
  {
    tone: 'violet',
    badgeText: 'Case study',
    badgeColor: '#C4B5FD',
    title: 'Pactify',
    description:
      'A quarterly BAS review that used to take six to seven hours now finishes in one, with consultancy fees cut in half.',
    ctaText: 'Read the story',
    href: '/industries/pactify',
    imageUrl: '/qll/industries/accounting.png',
  },
];

const presenceMapDots = [
  {
    start: { lat: 1.2868, lng: 103.8545, label: 'Singapore', side: 'singapore' },
    end: { lat: 39.1582, lng: -75.5244, label: 'USA', side: 'usa' },
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
  {
    start: { lat: 1.2868, lng: 103.8545 },
    end: { lat: 51.0447, lng: -114.0719, label: 'Canada', side: 'canada' },
  },
  {
    start: { lat: 1.2868, lng: 103.8545 },
    end: { lat: 25.2048, lng: 55.2708, label: 'Dubai', side: 'dubai' },
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

export default function QuantumLedgerLinkPage() {
  const [videoPlaying, setVideoPlaying] = useState(false);
  const [teamVideoPlaying, setTeamVideoPlaying] = useState(false);
  const [invoiceVideoPlaying, setInvoiceVideoPlaying] = useState(false);
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
              <span className="hero-mark" aria-hidden="true" />
              <p className="hero-tabs r">
                <span>Invoice to pay</span>
                <span className="hero-tab-dot" aria-hidden="true">·</span>
                <span>Invoice to cash</span>
                <span className="hero-tab-dot" aria-hidden="true">·</span>
                <span>Team expenses mgt</span>
                <span className="hero-tab-dot" aria-hidden="true">·</span>
                <span>Document mgt</span>
              </p>
              <h1 className="h1 r">
                Bookkeeping in 3 Clicks.
              </h1>
              <div className="hero-lines">
                <p className="hero-support r">
                  Supporting the people behind the numbers.
                </p>
                <p className="lead r">
                  One intelligent system that runs finance work from capture to payment to audit.
                </p>
              </div>
              <div className="actions r in">
                <Link
                  className="btn btn-primary"
                  to={bookDemoPath}
                  style={{ background: '#2FD4B5', color: '#04161C' }}
                >
                  Book a demo
                </Link>
                <a
                  className="btn btn-ghost"
                  href={externalLinks.getStarted}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Start free
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
          </div>
        </section>

        <section className="s dark industry-strip" id="industries" aria-label="Industries">
          <div className="wrap">
            <h3 className="blabel industry-heading r">Industries</h3>
            <div className="industry-grid r">
              {industryCards.map((card) => (
                <GradientCard key={card.href} {...card} />
              ))}
            </div>
          </div>
        </section>

        <IntegrationsSection variant="marquee" />

        <div id="product" className="product-block">
        <ProblemSolutionSection />
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

            {howFlows.map((flow, index) => {
              const howVideo = {
                'Invoice to Pay': {
                  playing: invoiceVideoPlaying,
                  onPlay: () => setInvoiceVideoPlaying(true),
                  embed: INVOICE_YOUTUBE_EMBED,
                  title: 'Invoice to pay',
                  label: 'Play the invoice to pay video',
                  thumb: '/qll/invoice-to-pay-thumbnail.jpg',
                  alt: 'Invoice to pay video',
                },
                'Team Expenses Mgt': {
                  playing: teamVideoPlaying,
                  onPlay: () => setTeamVideoPlaying(true),
                  embed: TEAM_YOUTUBE_EMBED,
                  title: 'Team expenses management',
                  label: 'Play the team expenses video',
                  thumb: '/qll/team-expense-thumbnail.jpg',
                  alt: 'Team expenses video',
                },
              }[flow.title];

              if (howVideo) {
                return (
                <div
                  key={flow.title}
                  className="video how-tab-video r"
                  role="tabpanel"
                  hidden={howTab !== index}
                >
                  {howVideo.playing ? (
                    <iframe
                      src={howVideo.embed}
                      title={howVideo.title}
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                      allowFullScreen
                      referrerPolicy="strict-origin-when-cross-origin"
                    />
                  ) : (
                    <button
                      className="video-btn"
                      type="button"
                      aria-label={howVideo.label}
                      onClick={howVideo.onPlay}
                    >
                      <img
                        src={howVideo.thumb}
                        alt={howVideo.alt}
                        width="1280"
                        height="720"
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
                );
              }

              return (
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
              );
            })}
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
          </div>
        </section>

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

          </div>
        </section>

        <section className="s paper" id="team">
          <div className="wrap">
            <p className="eyebrow r">Why us</p>
            <h2 className="h2 r">Founder-led. Globally distributed.</h2>
            <p className="team-proof r">
              <span>Tested by Accountants.</span>
              <span className="team-proof-dot" aria-hidden="true" />
              <span>Purpose built product for bookkeeping.</span>
            </p>
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

        <section className="s dark ink2 close" id="close">
          <div className="wrap">
            <p className="eyebrow r">Next step</p>
            <h2 className="h2 r">See it run on your own invoices.</h2>
            <p className="lead r">
              Book a 20-minute call. We run your volume through the model and give you a written
              implementation plan.
            </p>
            <div className="actions r">
              <Link
                className="btn btn-primary"
                to={bookDemoPath}
                style={{ background: '#2FD4B5', color: '#04161C' }}
              >
                Book a demo
              </Link>
              <a className="btn btn-ghost" href="mailto:sales@highvolt.tech">
                Talk to us
              </a>
            </div>
            <p className="contacts r">
              <a href="mailto:sales@highvolt.tech">sales@highvolt.tech</a>
            </p>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
