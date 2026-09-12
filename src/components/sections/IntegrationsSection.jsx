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
    <section id="integrations" className="s dark">
      <div className="wrap">
        <div className="integrations-layout">
          <div>
            <p className="eyebrow">Integrations</p>
            <h2 className="h2">Seamless integrations for your financial workflow</h2>
            <p className="lead">
              Sync payments, banking, and accounting tools to automate your workflow and keep your financial
              data accurate and up to date.
            </p>
          </div>

          <div className="integration-cloud-column">
            <IntegrationCloud />
          </div>
        </div>
      </div>
    </section>
  );
}
