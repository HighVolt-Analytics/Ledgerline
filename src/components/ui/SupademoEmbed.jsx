import { SUPADEMO_EMBED_SRC } from '../../data/navigation';

export default function SupademoEmbed({ title = 'Highvolt Demo', className = '' }) {
  return (
    <div
      className={className}
      style={{
        position: 'relative',
        boxSizing: 'content-box',
        maxHeight: '80svh',
        width: '100%',
        aspectRatio: '2.21',
        padding: '40px 0',
      }}
    >
      <iframe
        src={SUPADEMO_EMBED_SRC}
        loading="eager"
        title={title}
        allow="clipboard-write"
        allowFullScreen
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          border: 0,
        }}
      />
    </div>
  );
}
