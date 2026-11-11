import { useEffect, useLayoutEffect } from 'react';
import Header from '../components/layout/Header';
import SiteFooter from '../components/layout/SiteFooter';
import StoryShareButton from '../components/StoryShareButton';
import { externalLinks } from '../data/navigation';
import '../qll.css';

function jumpToTop() {
  if ('scrollRestoration' in window.history) {
    window.history.scrollRestoration = 'manual';
  }
  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
}

function StorySection({ section }) {
  return (
    <section className="story-row">
      <p className="story-row__label">{section.label}</p>
      <div className="story-row__content">
        {section.paragraphs?.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
        {section.bullets?.length ? (
          <ul>
            {section.bullets.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}

export default function CaseStudyPage({ study }) {
  const path = `/industries/${study.slug}`;
  const shareUrl = typeof window !== 'undefined' ? `${window.location.origin}${path}` : path;
  const title = `${study.company} case study — Quantum Ledger Line`;

  useLayoutEffect(() => {
    jumpToTop();
  }, []);

  useEffect(() => {
    document.body.classList.add('qll-page');
    jumpToTop();
    const retry = window.setTimeout(jumpToTop, 0);
    document.title = title;
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute('content', study.resultRest);
    return () => {
      window.clearTimeout(retry);
      document.body.classList.remove('qll-page');
    };
  }, [title, study.resultRest]);

  return (
    <div className="qll-site story-shell">
      <Header />
      <main className="story-page" data-industry={study.slug}>
        <section className="story-hero">
          <img
            className="story-hero__media"
            src={study.heroImage}
            alt=""
            aria-hidden
            decoding="async"
            fetchPriority="high"
          />
          <div className="story-hero__veil" aria-hidden />
          <div className="story-hero__inner">
            <div className="story-hero__brands">
              <span className="story-hero__brand">Quantum Ledger Line</span>
              <span className="story-hero__divider" aria-hidden />
              <span className="story-hero__brand story-hero__brand--partner">
                {study.company}
                <span className="story-hero__sector-inline"> · {study.sector}</span>
              </span>
            </div>

            <h1 className="story-hero__title">
              {study.heroPrimary}
              <br />
              {study.heroSecondary}
            </h1>

            <div className="story-hero__actions">
              <a className="story-hero__cta" href="#story-body">
                See full case study
              </a>
              <StoryShareButton url={shareUrl} title={title} />
            </div>
          </div>
        </section>

        <div className="story-body" id="story-body">
          <section className="story-result">
            <h2 className="story-result__title">
              <span className="story-result__metric">{study.resultMetric}</span>{' '}
              {study.resultRest}
            </h2>
          </section>

          {study.storySections.map((section, index) => (
            <StorySection key={`${section.label}-${index}`} section={section} />
          ))}

          <section className="story-row">
            <p className="story-row__label">About {study.company}</p>
            <div className="story-row__content">
              <p>{study.about}</p>
            </div>
          </section>
        </div>

      </main>

      <section className="s dark ink2 close" id="close">
        <div className="wrap">
          <p className="eyebrow r in">Next step</p>
          <h2 className="h2 r in">See it run on your own invoices.</h2>
          <p className="lead r in">
            Book a 20-minute call. We run your volume through the model and give you a written
            implementation plan.
          </p>
          <div className="actions r in">
            <a
              className="btn btn-primary"
              href={externalLinks.getStarted}
              target="_blank"
              rel="noopener noreferrer"
            >
              Start free
            </a>
            <a className="btn btn-ghost" href="mailto:sales@highvolt.tech">
              Talk to us
            </a>
          </div>
          <p className="contacts r in">
            <a href="mailto:sales@highvolt.tech">sales@highvolt.tech</a>
          </p>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
