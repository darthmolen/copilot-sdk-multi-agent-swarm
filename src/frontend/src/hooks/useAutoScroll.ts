import { useEffect, useRef, type RefObject } from 'react';

/**
 * Auto-scroll a container to the bottom when dependencies change,
 * unless the user has manually scrolled away.
 *
 * Ported from vscode-copilot-cli-extension MessageDisplay auto-scroll logic.
 */
export function useAutoScroll(
  containerRef: RefObject<HTMLElement | null>,
  deps: unknown[],
) {
  const userHasScrolled = useRef(false);
  const isProgrammaticScroll = useRef(false);

  // Track user scroll
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handler = () => {
      if (isProgrammaticScroll.current) return;
      const threshold = 100;
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (distFromBottom >= threshold) {
        userHasScrolled.current = true;
      } else {
        userHasScrolled.current = false;
      }
    };

    el.addEventListener('scroll', handler, { passive: true });
    return () => el.removeEventListener('scroll', handler);
  }, [containerRef]);

  // Auto-scroll on dependency change
  useEffect(() => {
    if (userHasScrolled.current) return;
    const el = containerRef.current;
    if (!el) return;

    isProgrammaticScroll.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => {
      isProgrammaticScroll.current = false;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
