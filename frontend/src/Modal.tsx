import { useLayoutEffect, useRef } from 'react';
import type { ReactNode } from 'react';

// Keep all keyboard interaction inside the active dialog and restore the trigger.
export function Modal({ titleId, onClose, children, busy = false, className = '' }: { titleId: string; onClose: () => void; children: ReactNode; busy?: boolean; className?: string }) {
  const panel = useRef<HTMLElement>(null);
  // Capture before children mount: React's autoFocus has already run by layout effects.
  const returnFocus = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const close = useRef(onClose);
  const blocked = useRef(busy);
  close.current = onClose; blocked.current = busy;
  useLayoutEffect(() => {
    const previous = returnFocus.current;
    const target = panel.current;
    if (!target) return;
    const focusables = () => Array.from(target.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])')).filter(el => !el.hasAttribute('disabled') && el.getClientRects().length);
    const first = target.querySelector<HTMLElement>('[autofocus], [data-autofocus]') || focusables()[0] || target;
    first.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (!blocked.current) close.current(); }
      if (event.key !== 'Tab') return;
      const items = focusables();
      const firstItem = items[0]; const lastItem = items.at(-1);
      if (!firstItem) { event.preventDefault(); target!.focus(); return; }
      if (event.shiftKey && (document.activeElement === firstItem || document.activeElement === target)) { event.preventDefault(); lastItem!.focus(); }
      else if (!event.shiftKey && document.activeElement === lastItem) { event.preventDefault(); firstItem.focus(); }
    }
    function containFocus(event: FocusEvent) { if (event.target instanceof Node && !target!.contains(event.target)) (focusables()[0] || target!).focus(); }
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('focusin', containFocus);
    const oldOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey, true); document.removeEventListener('focusin', containFocus); document.body.style.overflow = oldOverflow; if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div className="modal-backdrop" onClick={() => { if (!busy) onClose(); }}><section ref={panel} className={`modal ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onClick={e => e.stopPropagation()}>{children}</section></div>;
}
