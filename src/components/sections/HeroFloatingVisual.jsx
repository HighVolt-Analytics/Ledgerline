import { motion } from 'framer-motion';
import { assets } from '../../data/assets';

const EASE = [0.16, 1, 0.3, 1];

export default function HeroFloatingVisual() {
  return (
    <motion.div
      className="hero-visual"
      initial={{ opacity: 0, y: 28 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 1, ease: EASE, delay: 0.28 }}
    >
      <div className="hero-visual__stage">
        <img
          src={assets.hero}
          alt="Ledgerline invoice-to-payment automation dashboard"
          className="hero-visual__img"
          loading="eager"
          decoding="async"
        />
        <div className="hero-visual__fade-top" aria-hidden="true" />
        <div className="hero-visual__fade-bottom" aria-hidden="true" />
        <div className="hero-visual__fade-sides" aria-hidden="true" />
      </div>
    </motion.div>
  );
}
