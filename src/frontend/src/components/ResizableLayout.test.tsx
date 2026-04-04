import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ResizableLayout } from './ResizableLayout';

describe('ResizableLayout', () => {
  // --- Backward compatibility (horizontal default) ---

  describe('horizontal mode (default)', () => {
    it('renders left and right children', () => {
      render(
        <ResizableLayout
          left={<div>Left Panel</div>}
          right={<div>Right Panel</div>}
        />
      );
      expect(screen.getByText('Left Panel')).toBeInTheDocument();
      expect(screen.getByText('Right Panel')).toBeInTheDocument();
    });

    it('does NOT add the vertical modifier class', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
        />
      );
      const layout = container.querySelector('.resizable-layout');
      expect(layout).not.toHaveClass('resizable-layout--vertical');
    });

    it('applies col-resize cursor to body on mousedown', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
        />
      );
      const divider = container.querySelector('.resizable-layout__divider')!;
      fireEvent.mouseDown(divider);
      expect(document.body.style.cursor).toBe('col-resize');

      // Clean up
      fireEvent.mouseUp(document);
    });

    it('uses defaultLeftPercent for initial flex-basis', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
          defaultLeftPercent={30}
        />
      );
      const leftPane = container.querySelector('.resizable-layout__left') as HTMLElement;
      expect(leftPane.style.flexBasis).toBe('30%');
    });

    it('defaults to direction horizontal when not specified', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
        />
      );
      const layout = container.querySelector('.resizable-layout');
      expect(layout).toHaveClass('resizable-layout');
      expect(layout).not.toHaveClass('resizable-layout--vertical');
    });
  });

  // --- New vertical mode ---

  describe('vertical mode', () => {
    it('adds the vertical modifier class to container', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>Top</div>}
          right={<div>Bottom</div>}
          direction="vertical"
        />
      );
      const layout = container.querySelector('.resizable-layout');
      expect(layout).toHaveClass('resizable-layout--vertical');
    });

    it('renders left prop as top pane and right prop as bottom pane', () => {
      render(
        <ResizableLayout
          left={<div>Top Content</div>}
          right={<div>Bottom Content</div>}
          direction="vertical"
        />
      );
      expect(screen.getByText('Top Content')).toBeInTheDocument();
      expect(screen.getByText('Bottom Content')).toBeInTheDocument();
    });

    it('applies row-resize cursor to body on mousedown', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>Top</div>}
          right={<div>Bottom</div>}
          direction="vertical"
        />
      );
      const divider = container.querySelector('.resizable-layout__divider')!;
      fireEvent.mouseDown(divider);
      expect(document.body.style.cursor).toBe('row-resize');

      // Clean up
      fireEvent.mouseUp(document);
    });

    it('tracks clientY for vertical resizing on mousemove', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>Top</div>}
          right={<div>Bottom</div>}
          direction="vertical"
          defaultLeftPercent={50}
        />
      );

      const layout = container.querySelector('.resizable-layout') as HTMLElement;
      const divider = container.querySelector('.resizable-layout__divider')!;

      // Mock getBoundingClientRect for the container
      vi.spyOn(layout, 'getBoundingClientRect').mockReturnValue({
        top: 0,
        left: 0,
        bottom: 1000,
        right: 500,
        width: 500,
        height: 1000,
        x: 0,
        y: 0,
        toJSON: () => {},
      });

      fireEvent.mouseDown(divider);

      // Move to 30% from top (clientY = 300 out of height 1000)
      fireEvent.mouseMove(document, { clientY: 300 });

      const topPane = container.querySelector('.resizable-layout__left') as HTMLElement;
      expect(topPane.style.flexBasis).toBe('30%');

      fireEvent.mouseUp(document);
    });

    it('clamps vertical percentage between 20% and 80%', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>Top</div>}
          right={<div>Bottom</div>}
          direction="vertical"
          defaultLeftPercent={50}
        />
      );

      const layout = container.querySelector('.resizable-layout') as HTMLElement;
      const divider = container.querySelector('.resizable-layout__divider')!;

      vi.spyOn(layout, 'getBoundingClientRect').mockReturnValue({
        top: 0,
        left: 0,
        bottom: 1000,
        right: 500,
        width: 500,
        height: 1000,
        x: 0,
        y: 0,
        toJSON: () => {},
      });

      fireEvent.mouseDown(divider);

      // Try to drag beyond 80% (clientY = 900)
      fireEvent.mouseMove(document, { clientY: 900 });
      const topPane = container.querySelector('.resizable-layout__left') as HTMLElement;
      expect(topPane.style.flexBasis).toBe('80%');

      // Try to drag below 20% (clientY = 50)
      fireEvent.mouseMove(document, { clientY: 50 });
      expect(topPane.style.flexBasis).toBe('20%');

      fireEvent.mouseUp(document);
    });
  });

  // --- Explicit horizontal direction ---

  describe('explicit horizontal direction', () => {
    it('does NOT add vertical class when direction is horizontal', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
          direction="horizontal"
        />
      );
      const layout = container.querySelector('.resizable-layout');
      expect(layout).not.toHaveClass('resizable-layout--vertical');
    });

    it('applies col-resize cursor when direction is explicitly horizontal', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
          direction="horizontal"
        />
      );
      const divider = container.querySelector('.resizable-layout__divider')!;
      fireEvent.mouseDown(divider);
      expect(document.body.style.cursor).toBe('col-resize');

      fireEvent.mouseUp(document);
    });

    it('tracks clientX for horizontal resizing on mousemove', () => {
      const { container } = render(
        <ResizableLayout
          left={<div>L</div>}
          right={<div>R</div>}
          direction="horizontal"
          defaultLeftPercent={50}
        />
      );

      const layout = container.querySelector('.resizable-layout') as HTMLElement;
      const divider = container.querySelector('.resizable-layout__divider')!;

      vi.spyOn(layout, 'getBoundingClientRect').mockReturnValue({
        top: 0,
        left: 0,
        bottom: 500,
        right: 1000,
        width: 1000,
        height: 500,
        x: 0,
        y: 0,
        toJSON: () => {},
      });

      fireEvent.mouseDown(divider);

      // Move to 40% from left (clientX = 400 out of width 1000)
      fireEvent.mouseMove(document, { clientX: 400 });

      const leftPane = container.querySelector('.resizable-layout__left') as HTMLElement;
      expect(leftPane.style.flexBasis).toBe('40%');

      fireEvent.mouseUp(document);
    });
  });
});
