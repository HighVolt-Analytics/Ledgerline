import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import { integrations } from '../../data/sections';
import { integrationLogoMap } from '../../data/integrationLogos';

const ROW_SIZES = [5, 6, 5];

function buildRows(items) {
  let offset = 0;
  return ROW_SIZES.map((size) => {
    const row = items.slice(offset, offset + size);
    offset += size;
    return row;
  });
}

const ROWS = buildRows(integrations);

function IntegrationTile({ name, fade }) {
  const logo = integrationLogoMap[name];

  return (
    <div
      className={`integration-tile${fade ? ` integration-tile--fade-${fade}` : ''}`}
      title={name}
    >
      <div className="integration-tile-logo-wrap">
        <div
          className="integration-tile-logo"
          role="img"
          aria-label={name}
          dangerouslySetInnerHTML={{ __html: logo }}
        />
      </div>
    </div>
  );
}

function IntegrationCloud() {
  return (
    <div className="integration-cloud-wrap">
      <div className="integration-cloud" aria-label="Supported integrations">
        {ROWS.map((row, rowIndex) => (
          <div key={rowIndex} className="integration-cloud-row">
            {row.map((name, colIndex) => {
              const fade =
                colIndex === 0 ? 'start' : colIndex === row.length - 1 ? 'end' : null;

              return <IntegrationTile key={name} name={name} fade={fade} />;
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function IntegrationsSection() {
  return (
    <section id="integrations" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div className="grid grid-cols-1 items-center gap-14 lg:grid-cols-2 lg:gap-16">
        <FadeIn>
          <SectionLabel>Integrations</SectionLabel>
          <h2 className="mt-4 max-w-md text-3xl font-medium leading-[1.12] tracking-[-0.03em] text-foreground sm:text-4xl lg:text-[2.65rem]">
            Seamless integrations for your financial workflow
          </h2>
          <p className="mt-5 max-w-md text-base leading-relaxed text-muted-foreground sm:text-lg">
            Sync payments, banking, and accounting tools to automate your workflow and keep your financial data
            accurate and up to date.
          </p>
          <a
            href="#pricing"
            className="mt-8 inline-flex items-center justify-center rounded-xl bg-primary px-6 py-3 text-sm font-medium text-primary-foreground shadow-[0_0_24px_hsl(var(--primary)/0.28)] transition-transform duration-200 hover:scale-[1.02] active:scale-100"
          >
            View integrations
          </a>
        </FadeIn>

        <FadeIn delay={0.08} className="integration-cloud-column flex w-full justify-center">
          <IntegrationCloud />
        </FadeIn>
      </div>
    </section>
  );
}
