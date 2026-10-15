import { useEffect, useId, useRef, useState } from 'react';

function linkedInShareUrl(url, title) {
  const text = `${title}\n\n${url}`;
  return `https://www.linkedin.com/feed/?shareActive=true&text=${encodeURIComponent(text)}`;
}

export default function StoryShareButton({
  url,
  title,
  className = '',
  heading = 'Share this customer story',
}) {
  const panelId = useId();
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const isLocalUrl = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(url);

  useEffect(() => {
    if (!open) return undefined;

    const onPointerDown = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      const input = document.createElement('input');
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setCopied(true);
    }
  };

  const nativeShare = async () => {
    if (!navigator.share) return;
    try {
      await navigator.share({ title, url, text: title });
      setOpen(false);
    } catch {
      /* cancelled */
    }
  };

  return (
    <div ref={rootRef} className={['story-share', open ? 'is-open' : '', className].filter(Boolean).join(' ')}>
      <button
        type="button"
        className="story-share__trigger"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <svg className="story-share__icon" viewBox="0 0 24 24" aria-hidden>
          <path
            fill="currentColor"
            d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"
          />
        </svg>
        Share
      </button>

      {open ? (
        <div className="story-share__panel" id={panelId} role="dialog" aria-label={heading}>
          <p className="story-share__heading">{heading}</p>
          <div className="story-share__url-row">
            <input className="story-share__url" type="text" value={url} readOnly aria-label="Story link" />
            <button type="button" className="story-share__copy" onClick={copyLink}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          {isLocalUrl ? (
            <p className="story-share__note">
              LinkedIn can only preview a public URL. Deploy the site, then share the live link.
            </p>
          ) : null}
          <div className="story-share__actions">
            <a
              className="story-share__action story-share__action--linkedin"
              href={linkedInShareUrl(url, title)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
            >
              LinkedIn
            </a>
            {'share' in navigator && typeof navigator.share === 'function' ? (
              <button type="button" className="story-share__action" onClick={nativeShare}>
                More…
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
