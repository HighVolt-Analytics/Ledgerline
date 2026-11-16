import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';

const cardMotion = {
  rest: { scale: 1, y: 0 },
  hover: { scale: 1.03, y: -4 },
};

const imageMotion = {
  rest: { scale: 1, rotate: 0 },
  hover: { scale: 1.1, rotate: 3 },
};

export default function GradientCard({
  tone = 'teal',
  badgeText,
  badgeColor,
  title,
  description,
  ctaText,
  href,
  imageUrl,
}) {
  const reduce = useReducedMotion();

  return (
    <motion.div
      className="industry-card-motion"
      variants={cardMotion}
      initial="rest"
      animate="rest"
      whileHover={reduce ? undefined : 'hover'}
    >
      <Link to={href} className={`industry-card industry-card--${tone}`}>
        <motion.img
          src={imageUrl}
          alt=""
          variants={imageMotion}
          transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 400, damping: 15 }}
          className="industry-card-art"
        />
        <div className="industry-card-body">
          <div className="industry-card-badge">
            <span className="industry-card-dot" style={{ backgroundColor: badgeColor }} />
            {badgeText}
          </div>
          <div className="industry-card-copy">
            <h3>{title}</h3>
            <p>{description}</p>
          </div>
          <span className="industry-card-cta">
            {ctaText}
            <ArrowRight size={16} aria-hidden="true" />
          </span>
        </div>
      </Link>
    </motion.div>
  );
}
