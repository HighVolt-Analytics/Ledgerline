import network from '../../../quantum-ledger-link-1/assets/Neon Integrations Network Banner.png';

export default function HeroIntegrations() {
  return (
    <div className="hero-integrations r" aria-label="Integrates with">
      <img
        className="hero-integrations-art"
        src={network}
        alt="Integrates with Microsoft, Google, Slack, WhatsApp, Viber, Tally, Xero, Odoo, QuickBooks, Microsoft Dynamics, and SAP."
        width="2116"
        height="743"
      />
    </div>
  );
}
