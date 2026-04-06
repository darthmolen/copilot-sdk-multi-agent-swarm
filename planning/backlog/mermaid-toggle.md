# Mermaid Diagram Toggle Control

## Problem

When the report preview re-renders, mermaid diagrams disappear and raw code is left behind. The VSCode extension has a toolbar that lets users flip between rendered diagram and source code.

## Reference

`research/vscode-extension-copilot-cli/src/webview/app/components/MessageDisplay/MessageDisplay.js` lines 664-728

### Extension approach:
- Replaces `<pre><code class="language-mermaid">` with `.mermaid-render` container
- Container has: toolbar (View Source + Save Image buttons) + diagram div + source div
- Toggle swaps `.hidden` class between diagram and source
- Lazy-loads mermaid@11 from CDN, caches module
- Tracks processed blocks to avoid re-processing on re-render

### Our current approach (`useMermaid.ts`):
- React hook with `processedRef` Set to track processed blocks
- Uses `mermaid.render(id, source)` — works initially but DOM gets wiped on React re-render
- No toggle control, no toolbar

## Solution

Rewrite `useMermaid` hook to:
1. Replace `<pre>` with a persistent container (toolbar + diagram + source)
2. Add View Source / View Diagram toggle buttons
3. Render SVG into diagram div, keep source in hidden div
4. Track processed blocks to survive re-renders
5. Consider using `mermaid.run()` instead of `mermaid.render()` for DOM-based rendering

## CSS needed
- `.mermaid-render` — container with border, centered
- `.mermaid-toolbar` — flex end, gap
- `.mermaid-toolbar__btn` — small buttons matching dark theme
- `.mermaid-source` — pre-formatted code view
- `.hidden` — display none
