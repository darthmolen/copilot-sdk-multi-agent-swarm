import { useState, useRef, useCallback, type ReactNode } from 'react';

interface ResizableLayoutProps {
  left: ReactNode;
  right: ReactNode;
  defaultLeftPercent?: number;
}

export function ResizableLayout({
  left,
  right,
  defaultLeftPercent = 50,
}: ResizableLayoutProps) {
  const [leftPercent, setLeftPercent] = useState(defaultLeftPercent);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const handleMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
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
  }, []);

  return (
    <div ref={containerRef} className="resizable-layout">
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
