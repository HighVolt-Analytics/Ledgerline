import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';
import { pactifyCaseStudy } from '../data/pactifyCaseStudy';
import { spectraCaseStudy } from '../data/spectraCaseStudy';

const caseStudies = [
  {
    company: spectraCaseStudy.company,
    sector: spectraCaseStudy.sector,
    image: spectraCaseStudy.heroImage,
    href: `/industries/${spectraCaseStudy.slug}`,
    metric: '1',
    metricLabel: 'invoice number traces the full shipment',
    headline: 'Scattered trade documents, posted as one audit-ready ledger entry.',
    blurb:
      'Email, scans, and multi-page PDFs get classified, matched on the commercial invoice, and posted — across languages, currencies, and countries.',
  },
  {
    company: pactifyCaseStudy.company,
    sector: pactifyCaseStudy.sector,
    image: pactifyCaseStudy.heroImage,
    href: `/industries/${pactifyCaseStudy.slug}`,
    metric: '1 hr',
    metricLabel: 'down from a 6–7 hour BAS review',
    headline: 'A quarterly invoice pile, finished in the time it takes to review.',
    blurb:
      'Invoice to Pay pulls 120–150 invoices from email and Slack, drafts the entries, and cut consultancy fees for the work by 50%.',
  },
];

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
    document.title = 'Resources — Quantum Ledger Line';
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
            Case studies, guides, and support
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground sm:text-base">
            Stories from teams that moved documents and ledger posting onto Quantum Ledger Line,
            plus the guides to evaluate and roll it out.
          </p>
        </div>

        <section aria-labelledby="case-studies-heading">
          <div className="mb-5 flex items-end justify-between gap-4">
            <h2 id="case-studies-heading" className="text-lg font-medium tracking-tight text-foreground">
              Case studies
            </h2>
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-primary">Featured</p>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            {caseStudies.map((study) => (
              <article key={study.href} className="study-card">
                <div className="study-card__media">
                  <img src={study.image} alt="" />
                  <div className="study-card__veil" aria-hidden />
                  <p className="study-card__company">
                    {study.company}
                    <span>{study.sector}</span>
                  </p>
                  <p className="study-card__metric">
                    <span>{study.metric}</span>
                    <span className="study-card__metric-label">{study.metricLabel}</span>
                  </p>
                </div>

                <div className="study-card__body">
                  <h3>{study.headline}</h3>
                  <p>{study.blurb}</p>
                  <Link className="study-cta" to={study.href}>
                    <span>
                      Read the {study.company} story
                      <ArrowRight aria-hidden="true" />
                    </span>
                  </Link>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="mt-14" aria-labelledby="guides-heading">
          <h2 id="guides-heading" className="mb-5 text-lg font-medium tracking-tight text-foreground">
            Guides
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {resources.map((item) => (
              <article
                key={item.title}
                className="rounded-2xl border border-border bg-card/60 p-5 sm:p-6"
              >
                <h3 className="text-lg font-medium tracking-tight text-foreground">{item.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{item.desc}</p>
              </article>
            ))}
          </div>
        </section>

        <div className="mt-10 flex items-center gap-3 text-sm text-muted-foreground">
          <Logo className="h-7 sm:h-8" />
          <span>Quantum Ledger Line resources</span>
        </div>
      </main>
    </div>
  );
}
