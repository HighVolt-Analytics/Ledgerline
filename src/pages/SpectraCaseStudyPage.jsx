import { useEffect, useLayoutEffect } from 'react';
import { Link } from 'react-router-dom';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';
import StoryShareButton from '../components/StoryShareButton';
import {
  spectraCaseStudy,
  spectraStoryDescription,
  spectraStoryTitle,
} from '../data/spectraCaseStudy';
import { externalLinks } from '../data/navigation';
import '../qll.css';

const LINKEDIN_URL =
  'https://www.linkedin.com/company/high-volt-technology/posts/?feedView=all';

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

export default function SpectraCaseStudyPage() {
  const shareUrl = typeof window !== 'undefined' ? `${window.location.origin}/industries/spectra` : '/industries/spectra';
  const title = spectraStoryTitle();

  useLayoutEffect(() => {
    jumpToTop();
  }, []);

  useEffect(() => {
    document.body.classList.add('qll-page');
    jumpToTop();
    const retry = window.setTimeout(jumpToTop, 0);
    document.title = title;
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute('content', spectraStoryDescription());
    return () => {
      window.clearTimeout(retry);
      document.body.classList.remove('qll-page');
    };
  }, [title]);

  return (
    <div className="qll-site story-shell">
      <Header />
      <main className="story-page" data-industry="spectra">
        <section className="story-hero">
          <img
            className="story-hero__media"
            src={spectraCaseStudy.heroImage}
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
                {spectraCaseStudy.company}
                <span className="story-hero__sector-inline"> · {spectraCaseStudy.sector}</span>
              </span>
            </div>

            <h1 className="story-hero__title">
              {spectraCaseStudy.heroPrimary}
              <br />
              {spectraCaseStudy.heroSecondary}
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
              <span className="story-result__metric">{spectraCaseStudy.resultMetric}</span>{' '}
              {spectraCaseStudy.resultRest}
            </h2>
          </section>

          {spectraCaseStudy.storySections.map((section, index) => (
            <StorySection key={`${section.label}-${index}`} section={section} />
          ))}

          <section className="story-row">
            <p className="story-row__label">About {spectraCaseStudy.company}</p>
            <div className="story-row__content">
              <p>{spectraCaseStudy.about}</p>
            </div>
          </section>
        </div>

        <section className="story-cta" id="pilot" aria-labelledby="story-banner-title">
          <div className="story-cta__inner">
            <h2 id="story-banner-title" className="story-cta__title">
              See Quantum Ledger Line in action
            </h2>
            <p className="story-cta__lead">Start your journey with us.</p>
            <div className="story-cta__actions">
              <Link className="story-banner__back" to="/#audience">
                ← All industries
              </Link>
              <a
                className="btn btn-primary"
                href={externalLinks.getStarted}
                target="_blank"
                rel="noopener noreferrer"
              >
                Start free
              </a>
              <a className="story-cta__link" href={LINKEDIN_URL} target="_blank" rel="noopener noreferrer">
                Connect with us →
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="foot dark">
        <div className="wrap footin">
          <span className="fbrand">
            <Logo className="h-7 sm:h-8" />
            Quantum Ledger Line
          </span>
          <span className="flinks">
            <a href="https://quantumledgerline.com" target="_blank" rel="noopener noreferrer">
              quantumledgerline.com
            </a>
            <a href="https://highvolt.tech" target="_blank" rel="noopener noreferrer">
              highvolt.tech
            </a>
          </span>
        </div>
      </footer>
    </div>
  );
}
