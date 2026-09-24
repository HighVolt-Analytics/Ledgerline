import { useLayoutEffect, useRef, useState } from 'react';
import {
  Mail,
  Building2,
  Users,
  Database,
  FileText,
  FolderOpen,
  UserRound,
  AlertTriangle,
  Wallet,
  Clock,
  Inbox,
  Shield,
  UserCheck,
  Banknote,
  CheckCircle2,
  Timer,
  Target,
  Zap,
  ChevronRight,
} from 'lucide-react';
import Logo from '../ui/Logo';
import whatsapp from '../../assets/integrations/whatsapp.svg';
import googledrive from '../../assets/integrations/googledrive.svg';

const SOURCES = [
  { title: 'Email', sub: 'Invoices', icon: <Mail strokeWidth={1.75} /> },
  { title: 'WhatsApp', sub: 'Receipts', icon: <img src={whatsapp} alt="" /> },
  { title: 'Drive / Folders', sub: 'Documents', icon: <img src={googledrive} alt="" /> },
  { title: 'Vendors', sub: 'Bills', icon: <Building2 strokeWidth={1.75} /> },
  { title: 'Employees', sub: 'Expenses', icon: <Users strokeWidth={1.75} /> },
  { title: 'Other Systems', sub: 'PDFs / Data', icon: <Database strokeWidth={1.75} /> },
];

const PROBLEMS = [
  { title: 'Manual data entry', icon: <FileText strokeWidth={1.75} /> },
  { title: 'Manual classification and filing', icon: <FolderOpen strokeWidth={1.75} /> },
  { title: 'Approvals chased manually', icon: <UserRound strokeWidth={1.75} /> },
  { title: 'Duplicates and errors found late', icon: <AlertTriangle strokeWidth={1.75} /> },
  { title: 'Payment disconnected from workflow', icon: <Wallet strokeWidth={1.75} /> },
  { title: 'Records spread across systems', icon: <Database strokeWidth={1.75} /> },
  { title: 'Finance spends time processing', icon: <Clock strokeWidth={1.75} /> },
];

const STEPS = [
  { title: 'Capture', sub: 'From authorised channels', icon: <Inbox strokeWidth={1.75} /> },
  { title: 'Understand', sub: 'AI reads and extracts data', icon: <FileText strokeWidth={1.75} /> },
  { title: 'Classify & Store', sub: 'Automatically organised', icon: <FolderOpen strokeWidth={1.75} /> },
  { title: 'Approve', sub: 'Intelligently routed', icon: <UserCheck strokeWidth={1.75} /> },
  { title: 'Detect', sub: 'Duplicates and exceptions', icon: <Shield strokeWidth={1.75} /> },
  { title: 'Pay', sub: 'Invoice, approval and payment connected', icon: <Banknote strokeWidth={1.75} /> },
  { title: 'Record', sub: 'Audit-ready, always', icon: <Database strokeWidth={1.75} /> },
];

function mid(el, sr) {
  const r = el.getBoundingClientRect();
  return {
    left: r.left - sr.left,
    right: r.right - sr.left,
    cy: r.top + r.height / 2 - sr.top,
  };
}

function hubEdge(hx, hy, radius, x, y) {
  const dx = x - hx;
  const dy = y - hy;
  const len = Math.hypot(dx, dy) || 1;
  return [hx + (dx / len) * radius, hy + (dy / len) * radius];
}

function toHub(cardX, cardY, hx, hy, radius) {
  const [ex, ey] = hubEdge(hx, hy, radius, cardX, cardY);
  const c1x = cardX + (ex - cardX) * 0.5;
  return `M ${cardX} ${cardY} C ${c1x} ${cardY}, ${ex} ${ey}, ${ex} ${ey}`;
}

function fromHub(hx, hy, radius, cardX, cardY, scale = 1) {
  const [ex, ey] = hubEdge(hx, hy, radius, cardX, cardY);
  const dir = cardX >= hx ? 1 : -1;
  const c1x = ex + dir * Math.max(24 * scale, Math.abs(cardX - ex) * 0.28 * scale);
  const c2x = cardX - dir * 32 * scale;
  return {
    d: `M ${ex} ${ey} C ${c1x} ${ey}, ${c2x} ${cardY}, ${cardX} ${cardY}`,
    dot: { x: cardX, y: cardY },
  };
}

function Chip({ icon, title, sub, variant, chipRef }) {
  return (
    <div ref={chipRef} className={`ps-chip ps-chip--${variant}`}>
      <span className="ps-chip-icon">{icon}</span>
      <span className="ps-chip-copy">
        <strong>{title}</strong>
        {sub ? <span>{sub}</span> : null}
      </span>
    </div>
  );
}

export default function ProblemSolutionSection() {
  const stageRef = useRef(null);
  const hubRef = useRef(null);
  const sourceRefs = useRef([]);
  const problemRefs = useRef([]);
  const rightRefs = useRef([]);
  const [paths, setPaths] = useState({
    feed: [],
    feedDots: [],
    left: [],
    right: [],
    dots: [],
    size: { w: 0, h: 0 },
  });

  useLayoutEffect(() => {
    const draw = () => {
      const empty = { feed: [], feedDots: [], left: [], right: [], dots: [], size: { w: 0, h: 0 } };
      const stage = stageRef.current;
      const hub = hubRef.current;
      if (!stage || !hub || window.innerWidth < 1100) {
        setPaths(empty);
        return;
      }

      const sr = stage.getBoundingClientRect();
      const hr = hub.getBoundingClientRect();
      const hx = hr.left + hr.width / 2 - sr.left;
      const hy = hr.top + hr.height / 2 - sr.top;
      const radius = hr.width / 2 - 1;

      const sources = sourceRefs.current.filter(Boolean).map((el) => mid(el, sr));
      const problems = problemRefs.current.filter(Boolean).map((el) => mid(el, sr));
      const steps = rightRefs.current.filter(Boolean).map((el) => mid(el, sr));
      if (!sources.length || !problems.length) {
        setPaths(empty);
        return;
      }

      const firstLeft = Math.min(...problems.map((p) => p.left));
      const firstTop = Math.min(...problems.map((p) => p.cy));
      const firstBottom = Math.max(...problems.map((p) => p.cy));
      const originR = (firstBottom - firstTop) / 2 + 8;
      const originX = firstLeft + originR;
      const originY = (firstTop + firstBottom) / 2;
      const branchedLeft = sources.map((source) => fromHub(originX, originY, originR, source.right, source.cy));
      const left = problems.map((problem) => toHub(problem.right, problem.cy, hx, hy, radius));
      const branchedRight = steps.map((step) => fromHub(hx, hy, radius, step.left, step.cy));

      setPaths({
        feed: branchedLeft.map((item) => item.d),
        feedDots: branchedLeft.map((item) => item.dot),
        left,
        right: branchedRight.map((item) => item.d),
        dots: branchedRight.map((item) => item.dot),
        size: { w: sr.width, h: sr.height },
      });
    };

    draw();
    requestAnimationFrame(draw);
    const observer = new ResizeObserver(draw);
    if (stageRef.current) observer.observe(stageRef.current);
    window.addEventListener('resize', draw);
    const timer = window.setTimeout(draw, 400);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', draw);
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <section className="s dark tight ps-section" id="problem">
      <div className="wrap">
        <p className="ps-kicker r">The problem &amp; the solution</p>
        <h2 className="ps-heading r">Right now, nobody can tell you what you owe.</h2>
        <p className="ps-lead r">
          Finance documents are scattered, manual and disconnected. Ledgerline brings everything together.
        </p>

        <div className="ps-board r">
          <div className="ps-heads">
            <div className="ps-pane ps-pane--today">
              <p className="ps-label ps-label--today">Today</p>
              <h3>Scattered. Manual. Risky.</h3>
              <p className="ps-sub">Documents everywhere. People stitching it together.</p>
            </div>
            <span />
            <div className="ps-pane ps-pane--ledger">
              <p className="ps-label ps-label--ledger">With Ledgerline</p>
              <h3>Captured. Connected. Controlled.</h3>
              <p className="ps-sub">End-to-end automation for your finance operations.</p>
            </div>
          </div>

          <div className="ps-stage" ref={stageRef}>
            {paths.size.w > 0 && (
              <svg
                className="ps-lines"
                viewBox={`0 0 ${paths.size.w} ${paths.size.h}`}
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                {paths.feed.map((d, i) => (
                  <path key={`f${i}`} d={d} className="ps-lines-teal" />
                ))}
                {paths.feedDots.map((dot, i) => (
                  <circle key={`fd${i}`} className="ps-line-dot" cx={dot.x} cy={dot.y} r="3.5" />
                ))}
                {paths.left.map((d, i) => (
                  <path key={`l${i}`} d={d} />
                ))}
                {paths.right.map((d, i) => (
                  <path key={`r${i}`} d={d} className="ps-lines-teal" />
                ))}
                {paths.dots.map((dot, i) => (
                  <circle key={`d${i}`} className="ps-line-dot" cx={dot.x} cy={dot.y} r="3.5" />
                ))}
              </svg>
            )}

            <div className="ps-today-cols">
                <div className="ps-col">
                  {SOURCES.map((item, index) => (
                    <Chip
                      key={item.title}
                      variant="dark"
                      icon={item.icon}
                      title={item.title}
                      sub={item.sub}
                      chipRef={(el) => {
                        sourceRefs.current[index] = el;
                      }}
                    />
                  ))}
                </div>
                <div className="ps-col">
                  {PROBLEMS.map((item, index) => (
                    <Chip
                      key={item.title}
                      variant="dark"
                      icon={item.icon}
                      title={item.title}
                      chipRef={(el) => {
                        problemRefs.current[index] = el;
                      }}
                    />
                  ))}
                </div>
              </div>

            <div className="ps-hub">
              <span className="ps-hub-flow" aria-hidden="true" />
              <span className="ps-hub-flow ps-hub-flow--ring" aria-hidden="true" />
              <span className="ps-hub-flow ps-hub-flow--pull" aria-hidden="true" />
              <div className="ps-hub-core" ref={hubRef}>
                <Logo className="ps-hub-mark" />
                <p>Ledgerline</p>
                <span>
                  From documents
                  <br />
                  to decisions
                </span>
              </div>
            </div>

            <div className="ps-ledger-row">
                <div className="ps-col ps-col--steps">
                  {STEPS.map((item, index) => (
                    <Chip
                      key={item.title}
                      variant="light"
                      icon={item.icon}
                      title={item.title}
                      sub={item.sub}
                      chipRef={(el) => {
                        rightRefs.current[index] = el;
                      }}
                    />
                  ))}
                </div>
                <ChevronRight className="ps-arrow" strokeWidth={2} aria-hidden="true" />
                <article className="ps-result">
                  <CheckCircle2 strokeWidth={2} aria-hidden="true" />
                  <h3>Finance that moves forward.</h3>
                  <p>
                    Less admin.
                    <br />
                    More control.
                    <br />
                    A stronger business.
                  </p>
                </article>
              </div>
          </div>

          <div className="ps-outcome">
            <div className="ps-outcome-copy">
              <p className="ps-label ps-label--ledger">The outcome</p>
              <h3>
                Real impact.
                <br />
                Measurable results.
              </h3>
            </div>
            <ul>
              <li>
                <Timer strokeWidth={1.75} aria-hidden="true" />
                <strong>98%</strong>
                <span>Less processing time</span>
              </li>
              <li>
                <Target strokeWidth={1.75} aria-hidden="true" />
                <strong>99%</strong>
                <span>Accuracy. Duplicates and suspicious invoices flagged</span>
              </li>
              <li>
                <Zap strokeWidth={1.75} aria-hidden="true" />
                <strong>24/7</strong>
                <span>Finance operations</span>
              </li>
              <li>
                <Database strokeWidth={1.75} aria-hidden="true" />
                <strong>40%+</strong>
                <span>Cost savings*</span>
              </li>
              <li>
                <Users strokeWidth={1.75} aria-hidden="true" />
                <strong>People do what they do best</strong>
                <span>Think. Decide. Grow.</span>
              </li>
            </ul>
          </div>

          <p className="ps-foot">Invoices · Expenses · Payments · Records · All connected</p>
        </div>
      </div>
    </section>
  );
}
