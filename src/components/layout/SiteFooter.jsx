import Logo from '../ui/Logo';

export default function SiteFooter() {
  return (
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
  );
}
