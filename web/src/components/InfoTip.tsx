import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Info } from '@phosphor-icons/react';

/**
 * A small (i) that explains a term in plain words.
 *
 * Built on the native Popover API: it renders in the browser's top layer, so a
 * scrolling panel can never clip it, and Escape and click-outside dismissal come
 * free. Hover opens it for mouse users; tap and keyboard use the button itself.
 */
export default function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const id = `tip-${useId().replace(/:/g, '')}`;
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = pop.current;
    const b = btn.current;
    if (!p || !b) return;

    // Placed on open, next to the button and kept inside the viewport.
    const place = (e: Event) => {
      if ((e as ToggleEvent).newState !== 'open') return;
      const r = b.getBoundingClientRect();
      const w = Math.min(280, window.innerWidth - 24);
      p.style.width = `${w}px`;
      const left = Math.min(Math.max(12, r.left + r.width / 2 - w / 2), window.innerWidth - w - 12);
      let top = r.bottom + 8;
      if (top + p.offsetHeight > window.innerHeight - 12) top = r.top - p.offsetHeight - 8;
      p.style.left = `${left}px`;
      p.style.top = `${Math.max(12, top)}px`;
    };
    p.addEventListener('toggle', place);
    return () => p.removeEventListener('toggle', place);
  }, []);

  const show = () => { try { pop.current?.showPopover(); } catch { /* already open */ } };
  const hide = () => { try { pop.current?.hidePopover(); } catch { /* already closed */ } };

  return (
    <>
      <button
        ref={btn}
        type="button"
        className="info-btn"
        aria-label={label}
        aria-describedby={id}
        onMouseEnter={show}
        onMouseLeave={hide}
        {...{ popovertarget: id }}
      >
        <Info size={15} weight="bold" />
      </button>
      {/* A span, not a div: tips sit inside paragraphs, and a div there is invalid HTML. */}
      <span ref={pop} id={id} role="tooltip" className="info-pop" {...{ popover: 'auto' }}>
        {children}
      </span>
    </>
  );
}
