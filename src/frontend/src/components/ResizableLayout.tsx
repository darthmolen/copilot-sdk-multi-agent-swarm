import { useState, useRef, useCallback, type ReactNode } from 'react';

interface ResizableLayoutProps {
  left: ReactNode;
  right: ReactNode;
  defaultLeftPercent?: number;
  direction?: 'horizontal' | 'vertical';
}

export function ResizableLayout({
  left,
  right,
  defaultLeftPercent = 50,
  direction = 'horizontal',
}: ResizableLayoutProps) {
  const [leftPercent, setLeftPercent] = useState(defaultLeftPercent);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const isVertical = direction === 'vertical';

  const handleMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = isVertical ? 'row-resize' : 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();

      let pct: number;
      if (isVertical) {
        pct = ((e.clientY - rect.top) / rect.height) * 100;
      } else {
        pct = ((e.clientX - rect.left) / rect.width) * 100;
      }

      // Clamp between 20% and 80%
      setLeftPercent(Math.min(80, Math.max(20, pct)));
    };

    const handleMouseUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [isVertical]);

  const containerClass = [
    'resizable-layout',
    isVertical ? 'resizable-layout--vertical' : '',
  ].filter(Boolean).join(' ');

  return (
    <div ref={containerRef} className={containerClass}>
      <div className="resizable-layout__left" style={{ flexBasis: `${leftPercent}%` }}>
        {left}
      </div>
      <div
        className="resizable-layout__divider"
        onMouseDown={handleMouseDown}
      />
      <div className="resizable-layout__right" style={{ flexBasis: `${100 - leftPercent}%` }}>
        {right}
      </div>
    </div>
  );
}
