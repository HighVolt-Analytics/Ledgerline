import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';
import SupademoEmbed from '../components/ui/SupademoEmbed';

export const TOUR_DEMOS = [
  { slug: 'invoice-to-pay', title: 'Invoice to Pay', id: 'cmw0z86dt00t2qmx65nceofxy' },
  { slug: 'invoice-approval', title: 'Invoice Approval', id: null },
  { slug: 'employee-expense-claim', title: 'Employee Expense Claim', id: null },
  { slug: 'duplicate-invoice-check', title: 'Duplicate Invoice check', id: 'cmwnqiagu000c2w0jbrzczfgf' },
  { slug: 'bank-to-books', title: 'Bank to Books', id: 'cmwnsve6213bsqmk14j9jmpmw' },
];

function embedSrc(id) {
  return `https://app.supademo.com/embed/${id}?embed_v=2&utm_source=embed`;
}

export default function InteractiveTourPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('demo');
  const active = TOUR_DEMOS.find((demo) => demo.slug === requested) || TOUR_DEMOS[0];

  useEffect(() => {
    document.body.classList.remove('qll-page');
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header />
      <main className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-28 sm:px-6 sm:pt-32">
        <div className="mb-6">
          <p className="font-mono text-[12px] uppercase tracking-[0.28em] text-muted-foreground">
            Product walkthrough
          </p>
          <h1 className="mt-2 text-2xl font-medium tracking-tight text-foreground sm:text-3xl">
            Interactive Tour
          </h1>
        </div>

        <div className="mb-5 flex flex-wrap gap-2" role="tablist" aria-label="Interactive demos">
          {TOUR_DEMOS.map((demo) => {
            const selected = demo.slug === active.slug;
            return (
              <button
                key={demo.slug}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setParams({ demo: demo.slug })}
                className={`rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                  selected
                    ? 'border-white bg-white text-[#04161c]'
                    : 'border-white/70 bg-white/10 text-white hover:bg-white/20'
                }`}
              >
                {demo.title}
              </button>
            );
          })}
        </div>

        <div className="overflow-hidden rounded-2xl border border-white/20 bg-black shadow-lg">
          {active.id ? (
            <SupademoEmbed key={active.id} title={active.title} src={embedSrc(active.id)} />
          ) : null}
        </div>

        <div className="mt-8 flex items-center gap-3 text-sm text-muted-foreground">
          <Logo className="h-7 sm:h-8" />
          <span>Ledgerline interactive demo</span>
        </div>
      </main>
    </div>
  );
}
