import { useLayoutEffect, useRef, useState } from 'react';
import { FileText, Folder, UserRound, CreditCard, BarChart3, Check } from 'lucide-react';
import slack from '../../assets/integrations/slack.svg';

const CHECKS = [
  { label: 'Understand documents', icon: FileText },
  { label: 'File in the right folder', icon: Folder },
  { label: 'Process and send for approval', icon: UserRound },
  { label: 'Make payments', icon: CreditCard },
  { label: 'Post accounting entries', icon: BarChart3 },
];

function TeamsMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="17.7" cy="5.05" r="1.65" fill="#5059C9" />
      <path
        fill="#5059C9"
        d="M15.15 7.45h4.85c.42 0 .75.34.75.76v4.15a2.55 2.55 0 0 1-2.55 2.55h-.15a2.55 2.55 0 0 1-2.55-2.55V8.2c0-.42.33-.75.75-.75z"
      />
      <circle cx="12.15" cy="4.55" r="2.45" fill="#7B83EB" />
      <path
        fill="#7B83EB"
        d="M16.55 7.45H7.35c-.5 0-.9.4-.9.9v4.95a4.55 4.55 0 0 0 9.1 0V8.35c0-.5-.4-.9-.9-.9z"
      />
      <path fill="#fff" d="M8.05 10.05h4.7v1.2H10.5V16.3H9.3v-5.05H8.05z" />
    </svg>
  );
}

function GmailMark() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#4caf50" d="M45 16.2 40 18.95 35 23.7 35 40h7c1.657 0 3-1.343 3-3V16.2z" />
      <path fill="#1e88e5" d="M3 16.2 6.614 17.91 13 23.7V40H6c-1.657 0-3-1.343-3-3V16.2z" />
      <polygon fill="#e53935" points="35,11.2 24,19.45 13,11.2 12,17 13,23.7 24,31.95 35,23.7 36,17" />
      <path fill="#c62828" d="M3 12.298V16.2l10 7.5V11.2L9.876 8.859C9.132 8.301 8.228 8 7.298 8h0C4.924 8 3 9.924 3 12.298z" />
      <path fill="#fbc02d" d="M45 12.298V16.2l-10 7.5V11.2l3.124-2.341C38.868 8.301 39.772 8 40.702 8h0C43.076 8 45 9.924 45 12.298z" />
    </svg>
  );
}

function PdfMark() {
  return (
    <svg viewBox="0 0 40 48" aria-hidden="true">
      <path fill="#E2231A" d="M6 2h18.5L36 13.5V42a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4z" />
      <path fill="#FF8A80" d="M24.5 2V13.5H36" />
      <text x="19" y="34" textAnchor="middle" fill="#fff" fontSize="9" fontWeight="800" fontFamily="Arial, sans-serif">
        PDF
      </text>
    </svg>
  );
}

function ExcelMark() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#169154" d="M29 6H15.744C14.781 6 14 6.781 14 7.744v7.259h15V6z" />
      <path fill="#18482A" d="M14 33.054v7.202C14 41.219 14.781 42 15.743 42H29v-8.946H14z" />
      <path fill="#0C8045" d="M14 15.003h15V24H14z" />
      <path fill="#17472A" d="M14 24h15v9.054H14z" />
      <path fill="#29C27F" d="M42.256 6H29v9.003h15V7.744C44 6.781 43.219 6 42.256 6z" />
      <path fill="#27663F" d="M29 33.054V42h13.257C43.219 42 44 41.219 44 40.256v-7.202H29z" />
      <path fill="#19AC65" d="M29 15.003h15V24H29z" />
      <path fill="#129652" d="M29 24h15v9.054H29z" />
      <path fill="#0C7238" d="M22.319 34H5.681C4.753 34 4 33.247 4 32.319V15.681C4 14.753 4.753 14 5.681 14h16.638C23.247 14 24 14.753 24 15.681v16.638C24 33.247 23.247 34 22.319 34z" />
      <path fill="#fff" d="M9.807 19 12.444 23.6 9.7 28.399h2.1l1.65-3.1 1.62 3.1h2.13l-2.79-4.8 2.64-4.6h-2.07l-1.53 3.05L12.05 19H9.807z" />
    </svg>
  );
}

function WordMark() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#2196F3" d="M42 10.5v27c0 1.381-1.119 2.5-2.5 2.5H28V8h11.5C40.881 8 42 9.119 42 10.5z" />
      <path fill="#1565C0" d="M28 8H9.5C8.119 8 7 9.119 7 10.5v27C7 38.881 8.119 40 9.5 40H28V8z" />
      <path fill="#fff" d="M12.4 17.2h2.5l2.3 8.6 2.2-8.6h2.3l2.2 8.6 2.3-8.6h2.4L25.2 30.6h-2.4l-2.2-7.8-2.2 7.8h-2.4l-3.6-13.4z" />
    </svg>
  );
}

function DocMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#F7FBFF" d="M6.2 2.4h7.4L19.6 8.2v12.1c0 1-.8 1.8-1.8 1.8H6.2c-1 0-1.8-.8-1.8-1.8V4.2c0-1 .8-1.8 1.8-1.8z" />
      <path fill="#C5D6E2" d="M13.6 2.4V7.2c0 .7.5 1.2 1.2 1.2h4.8" />
      <path fill="#8AA3B4" d="M7.4 12h7.4v1.15H7.4zm0 2.45h7.4V15.6H7.4zm0 2.45h5.1v1.15H7.4z" />
    </svg>
  );
}

function flow(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const lead = Math.max(28, Math.abs(dx) * 0.72);
  const dir = dx >= 0 ? 1 : -1;
  const c1x = x1 + dir * lead;
  const c2x = x2 - dir * lead;
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${c1x.toFixed(1)} ${y1.toFixed(1)}, ${c2x.toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}

function docks(count, top, height) {
  const pad = height * 0.22;
  const start = top + pad;
  const end = top + height - pad;
  if (count <= 1) return [top + height / 2];
  return Array.from({ length: count }, (_, index) => start + ((end - start) * index) / (count - 1));
}

export default function ProblemSolutionSection() {
  const cardRef = useRef(null);
  const coreRef = useRef(null);
  const sourceRefs = useRef([]);
  const rowRefs = useRef([]);
  const [lines, setLines] = useState({ d: [], w: 0, h: 0 });

  useLayoutEffect(() => {
    const draw = () => {
      const card = cardRef.current;
      const core = coreRef.current;
      if (!card || !core || window.innerWidth < 720) {
        setLines({ d: [], w: 0, h: 0 });
        return;
      }
      const base = card.getBoundingClientRect();
      const hub = core.getBoundingClientRect();
      const leftX = hub.left - base.left;
      const rightX = hub.right - base.left;
      const hubTop = hub.top - base.top;
      const sources = sourceRefs.current.filter(Boolean);
      const rows = rowRefs.current.filter(Boolean);
      const leftDocks = docks(sources.length, hubTop, hub.height);
      const rightDocks = docks(rows.length, hubTop, hub.height);
      const paths = [];

      sources.forEach((el, index) => {
        const r = el.getBoundingClientRect();
        paths.push(flow(r.right - base.left, r.top + r.height / 2 - base.top, leftX, leftDocks[index]));
      });

      rows.forEach((el, index) => {
        const r = el.getBoundingClientRect();
        paths.push(flow(rightX, rightDocks[index], r.left - base.left, r.top + r.height / 2 - base.top));
      });

      setLines({ d: paths, w: base.width, h: base.height });
    };

    draw();
    const observer = new ResizeObserver(draw);
    if (cardRef.current) observer.observe(cardRef.current);
    window.addEventListener('resize', draw);
    const timer = window.setTimeout(draw, 300);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', draw);
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <section className="s dark ps-section" id="problem">
      <div className="wrap">
        <p className="ps-kicker r">
          <span>The problem &amp; the solution</span>
        </p>
        <h2 className="ps-heading r">
          Unorganised documents.
          <br />
          Manual work. No visibility.
        </h2>

        <div className="ps-compare r">
          <article className="ps-card ps-card--problem">
            <div className="ps-sol-copy">
              <p className="ps-label ps-label--problem">
                <span className="ps-label-mark" aria-hidden="true">
                  !
                </span>
                The problem
              </p>
              <p>
                Documents and files are scattered across multiple systems. Teams spend hours on data
                entry, searching invoices and documents, posting manual accounting entries, and working
                without an approval matrix or clear visibility.
              </p>
            </div>
            <div className="ps-vault" aria-hidden="true">
              <svg className="ps-vault-lines" viewBox="0 0 420 160" fill="none">
                <path d="M36 48 C 90 20, 140 70, 188 46" />
                <path d="M150 96 C 200 70, 240 110, 292 78" />
                <path d="M250 40 C 300 24, 340 70, 386 52" />
                <path d="M70 112 C 130 96, 180 128, 230 108" />
              </svg>
              <span className="ps-sheet ps-sheet--g" />
              <span className="ps-sheet ps-sheet--h" />
              <span className="ps-sheet ps-sheet--i" />
              <span className="ps-sheet ps-sheet--j" />
              <span className="ps-sheet ps-sheet--k" />
              <span className="ps-sheet ps-sheet--a" />
              <span className="ps-sheet ps-sheet--b" />
              <span className="ps-sheet ps-sheet--c" />
              <span className="ps-sheet ps-sheet--d" />
              <span className="ps-sheet ps-sheet--e" />
              <span className="ps-sheet ps-sheet--f" />
              <span className="ps-app ps-app--pdf">
                <PdfMark />
              </span>
              <span className="ps-app ps-app--xls">
                <ExcelMark />
              </span>
              <span className="ps-app ps-app--doc">
                <WordMark />
              </span>
            </div>
          </article>

          <span className="ps-join" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M5 12h12M13 6l6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>

          <article className="ps-card ps-card--solution">
            <div className="ps-sol-copy">
              <p className="ps-label ps-label--solution">
                <span className="ps-label-mark" aria-hidden="true">
                  <Check strokeWidth={3} />
                </span>
                The solution
              </p>
              <p>
                One system sits inside your communication channels, understands each document, files it
                in the right folder, processes it, sends it for approval, makes payments, and posts the
                accounting entries.
              </p>
            </div>
            <div className="ps-sol" ref={cardRef}>
            {lines.w > 0 && (
              <svg
                className="ps-sol-lines"
                width={lines.w}
                height={lines.h}
                viewBox={`0 0 ${lines.w} ${lines.h}`}
                aria-hidden="true"
              >
                {lines.d.map((d) => (
                  <path key={d} d={d} />
                ))}
              </svg>
            )}
              <div className="ps-sources">
                {[
                  { key: 'slack', node: <img src={slack} alt="" /> },
                  { key: 'teams', node: <TeamsMark /> },
                  { key: 'mail', node: <GmailMark /> },
                  { key: 'file', node: <DocMark /> },
                ].map((item, index) => (
                  <span
                    key={item.key}
                    className={`ps-node ps-node--${item.key}`}
                    ref={(el) => {
                      sourceRefs.current[index] = el;
                    }}
                  >
                    {item.node}
                  </span>
                ))}
              </div>
              <div className="ps-core" ref={coreRef}>
                <img className="ps-core-logo" src="/ledgerlink-logo.png" alt="" />
              </div>
              <ul className="ps-checks">
                  {CHECKS.map((item, index) => (
                    <li
                      key={item.label}
                      ref={(el) => {
                        rowRefs.current[index] = el;
                      }}
                    >
                      <item.icon strokeWidth={1.75} aria-hidden="true" />
                      <span>{item.label}</span>
                      <Check className="ps-tick" strokeWidth={3} aria-hidden="true" />
                    </li>
                  ))}
              </ul>
            </div>
          </article>
        </div>

        <p className="ps-closer r">
          Days to <span>minutes.</span>
        </p>
      </div>
    </section>
  );
}
