import { motion } from 'framer-motion';
import { assets } from '../../data/assets';

const EASE = [0.16, 1, 0.3, 1];

export default function HeroFloatingVisual() {
  return (
    <motion.div
      className="hero-visual"
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.85, ease: EASE, delay: 0.18 }}
    >
      <div className="hero-visual__glow" aria-hidden="true" />
      <img
        src={assets.hero}
        alt="Ledgerline invoice-to-payment automation dashboard"
        className="hero-visual__img"
        loading="eager"
        decoding="async"
      />
      <div className="hero-visual__fade-left" aria-hidden="true" />
      <div className="hero-visual__fade-bottom" aria-hidden="true" />
    </motion.div>
  );
}
