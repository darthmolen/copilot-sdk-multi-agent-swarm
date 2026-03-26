import { useEffect, useRef } from 'react';
import mermaid from 'mermaid';

let initialized = false;

function initMermaid() {
  if (initialized) return;
  mermaid.initialize({
    theme: 'dark',
    startOnLoad: false,
    securityLevel: 'loose',
  });
  initialized = true;
}

/**
 * Hook that scans a container ref for mermaid code blocks and renders them as SVG.
 * Also adds a "View Source" toggle to each rendered diagram.
 */
export function useMermaid(
  containerRef: React.RefObject<HTMLElement | null>,
  deps: unknown[] = [],
) {
  const processedRef = useRef(new Set<Element>());

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    initMermaid();

    // Find all mermaid code blocks not yet processed
    const codeBlocks = container.querySelectorAll(
      'code.language-mermaid, pre > code.language-mermaid'
    );

    const toProcess: Element[] = [];
    codeBlocks.forEach((block) => {
      const wrapper = block.closest('pre') ?? block;
      if (!processedRef.current.has(wrapper)) {
        processedRef.current.add(wrapper);
        toProcess.push(wrapper);
      }
    });

    if (toProcess.length === 0) return;

    // Process each mermaid block
    toProcess.forEach(async (wrapper) => {
      const codeEl = wrapper.tagName === 'PRE'
        ? wrapper.querySelector('code')
        : wrapper;
      if (!codeEl) return;

      const source = codeEl.textContent ?? '';
      if (!source.trim()) return;

      try {
        const id = `mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const { svg } = await mermaid.render(id, source.trim());

        // Create container with toggle
        const mermaidContainer = document.createElement('div');
        mermaidContainer.className = 'mermaid-container';

        const diagramDiv = document.createElement('div');
        diagramDiv.className = 'mermaid-diagram';
        diagramDiv.innerHTML = svg;

        const sourceDiv = document.createElement('div');
        sourceDiv.className = 'mermaid-source';
        sourceDiv.style.display = 'none';
        const pre = document.createElement('pre');
        const code = document.createElement('code');
        code.textContent = source.trim();
        pre.appendChild(code);
        sourceDiv.appendChild(pre);

        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'mermaid-toggle';
        toggleBtn.textContent = 'View Source';
        toggleBtn.addEventListener('click', () => {
          const showingSource = sourceDiv.style.display !== 'none';
          sourceDiv.style.display = showingSource ? 'none' : 'block';
          diagramDiv.style.display = showingSource ? 'block' : 'none';
          toggleBtn.textContent = showingSource ? 'View Source' : 'View Diagram';
        });

        mermaidContainer.appendChild(toggleBtn);
        mermaidContainer.appendChild(diagramDiv);
        mermaidContainer.appendChild(sourceDiv);

        wrapper.replaceWith(mermaidContainer);
      } catch (err) {
        // If mermaid fails to render, leave original code block
        console.warn('Mermaid render failed:', err);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
