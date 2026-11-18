import { TOUR_SUPADEMO_EMBED_SRC } from '../../data/navigation';

export default function SupademoEmbed({
  title = 'Submit, Approve, and Pay Expense Claims in HighVolt',
  src = TOUR_SUPADEMO_EMBED_SRC,
  className = '',
}) {
  return (
    <div className={`tour-frame ${className}`.trim()}>
      <iframe
        src={src}
        loading="eager"
        title={title}
        allow="clipboard-write"
        allowFullScreen
      />
    </div>
  );
}
