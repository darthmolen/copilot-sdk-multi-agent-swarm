import { useRef, useEffect, useState } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

interface StreamingMarkdownProps {
  content: string;
  isStreaming: boolean;
}

function renderMarkdown(md: string): string {
  return DOMPurify.sanitize(marked.parse(md) as string);
}

/**
 * Renders markdown content progressively during streaming,
 * flushing only complete markdown units to avoid broken rendering.
 *
 * When streaming ends, renders the full content.
 */
export function StreamingMarkdown({ content, isStreaming }: StreamingMarkdownProps) {
  const [html, setHtml] = useState('');
  const renderedUpTo = useRef(0);
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!isStreaming) {
      // Streaming done — render everything
      setHtml(renderMarkdown(content));
      renderedUpTo.current = content.length;
      return;
    }

    // During streaming, flush safe markdown units
    const unrendered = content.slice(renderedUpTo.current);
    const safeEnd = findSafeFlushPoint(unrendered);

    if (safeEnd > 0) {
      const safeChunk = content.slice(0, renderedUpTo.current + safeEnd);
      setHtml(renderMarkdown(safeChunk));
      renderedUpTo.current += safeEnd;
    }

    // Inactivity flush — if no new content in 1.5s, render what we have
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = setTimeout(() => {
      if (content.length > renderedUpTo.current) {
        setHtml(renderMarkdown(content));
        renderedUpTo.current = content.length;
      }
    }, 1500);

    return () => {
      if (flushTimer.current) clearTimeout(flushTimer.current);
    };
  }, [content, isStreaming]);

  // Reset when content resets (new message)
  useEffect(() => {
    if (content === '') {
      setHtml('');
      renderedUpTo.current = 0;
    }
  }, [content]);

  return (
    <div
      className="streaming-markdown"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/**
 * Find the last safe point to flush markdown without breaking structures.
 * Returns the number of characters from the start that are safe to render.
 */
function findSafeFlushPoint(text: string): number {
  let safePoint = 0;
  let i = 0;
  let inCodeFence = false;

  while (i < text.length) {
    // Code fence toggle
    if (text.startsWith('```', i)) {
      inCodeFence = !inCodeFence;
      if (!inCodeFence) {
        // End of code fence — find the end of the line
        const lineEnd = text.indexOf('\n', i + 3);
        if (lineEnd !== -1) {
          safePoint = lineEnd + 1;
          i = lineEnd + 1;
          continue;
        }
      }
      i += 3;
      continue;
    }

    if (inCodeFence) {
      i++;
      continue;
    }

    // Double newline = paragraph break — safe to flush
    if (text.startsWith('\n\n', i)) {
      safePoint = i + 2;
      i += 2;
      continue;
    }

    // Heading followed by newline
    if (text[i] === '#' && (i === 0 || text[i - 1] === '\n')) {
      const lineEnd = text.indexOf('\n', i);
      if (lineEnd !== -1) {
        safePoint = lineEnd + 1;
        i = lineEnd + 1;
        continue;
      }
    }

    i++;
  }

  return safePoint;
}
