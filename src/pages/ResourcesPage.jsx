import { useEffect } from 'react';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';

const resources = [
  {
    title: 'Product overview',
    desc: 'How Quantum Ledger Line handles invoices, expenses, and documents end to end.',
  },
  {
    title: 'Implementation guide',
    desc: 'Steps to connect your accounting stack and roll out with your finance team.',
  },
  {
    title: 'Security & compliance',
    desc: 'How we keep audit trails, approvals, and evidence locked down.',
  },
  {
    title: 'Help center',
    desc: 'Short answers for capture, approvals, syncing, and day-to-day finance work.',
  },
];

export default function ResourcesPage() {
  useEffect(() => {
    document.body.classList.remove('qll-page');
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header />
      <main className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-28 sm:px-6 sm:pt-32">
        <div className="mb-10">
          <p className="font-mono text-[12px] uppercase tracking-[0.28em] text-muted-foreground">
            Resources
          </p>
          <h1 className="mt-2 text-2xl font-medium tracking-tight text-foreground sm:text-3xl">
            Guides, docs, and support
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground sm:text-base">
            Everything you need to evaluate, roll out, and run Quantum Ledger Line with your team.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {resources.map((item) => (
            <article
              key={item.title}
              className="rounded-2xl border border-border bg-card/60 p-5 sm:p-6"
            >
              <h2 className="text-lg font-medium tracking-tight text-foreground">{item.title}</h2>
              <p className="mt-2 text-sm text-muted-foreground">{item.desc}</p>
            </article>
          ))}
        </div>

        <div className="mt-10 flex items-center gap-3 text-sm text-muted-foreground">
          <Logo className="h-7 sm:h-8" />
          <span>Quantum Ledger Line resources</span>
        </div>
      </main>
    </div>
  );
}
