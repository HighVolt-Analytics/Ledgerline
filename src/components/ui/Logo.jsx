import { assets } from '../../data/assets';

export default function Logo({ className = '' }) {
  return (
    <img
      src={assets.logo}
      alt="Quantum Ledgerlink"
      className={`h-9 w-auto object-contain sm:h-10 ${className}`}
    />
  );
}
