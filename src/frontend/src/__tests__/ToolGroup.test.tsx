import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { ToolGroup } from '../components/ToolGroup';
import type { ActiveTool } from '../types/swarm';

function makeTool(overrides: Partial<ActiveTool> = {}): ActiveTool {
  return {
    toolCallId: 'tc-1',
    toolName: 'read_file',
    status: 'running',
    ...overrides,
  };
}

describe('ToolGroup', () => {
  // 1. renders tool with name and running status icon
  it('renders tool with name and running status icon', () => {
    const tools: ActiveTool[] = [makeTool({ status: 'running' })];
    render(<ToolGroup tools={tools} />);

    expect(screen.getByText('read_file')).toBeTruthy();
    // Running icon is hourglass
    expect(screen.getByText('\u23F3')).toBeTruthy();
  });

  // 2. shows input preview when provided
  it('shows input preview when provided', () => {
    const tools: ActiveTool[] = [
      makeTool({
        status: 'running',
        input: 'This is a sample input for testing the tool group component preview',
      }),
    ];
    render(<ToolGroup tools={tools} />);

    // Input should be truncated to ~60 chars
    const inputEl = screen.getByTestId('tool-input-preview');
    expect(inputEl.textContent!.length).toBeLessThanOrEqual(63); // 60 + "..."
    expect(inputEl.textContent).toContain('This is a sample input');
  });

  // 3. auto-collapses when 2+ tools all complete (shows "N tools" summary)
  it('auto-collapses when 2+ tools all complete', () => {
    const tools: ActiveTool[] = [
      makeTool({ toolCallId: 'tc-1', toolName: 'read_file', status: 'complete' }),
      makeTool({ toolCallId: 'tc-2', toolName: 'write_file', status: 'complete' }),
      makeTool({ toolCallId: 'tc-3', toolName: 'bash', status: 'complete' }),
    ];
    render(<ToolGroup tools={tools} />);

    // Should show summary text
    expect(screen.getByText(/3 tools/)).toBeTruthy();
    // Individual tool names should NOT be visible as separate items
    expect(screen.queryByTestId('tool-group-item')).toBeNull();
  });

  // 4. expands when header clicked
  it('expands collapsed group when header clicked', () => {
    const tools: ActiveTool[] = [
      makeTool({ toolCallId: 'tc-1', toolName: 'read_file', status: 'complete' }),
      makeTool({ toolCallId: 'tc-2', toolName: 'write_file', status: 'complete' }),
    ];
    render(<ToolGroup tools={tools} />);

    // Should be collapsed initially
    expect(screen.queryByTestId('tool-group-item')).toBeNull();

    // Click header to expand
    fireEvent.click(screen.getByTestId('tool-group-header'));

    // Now items should be visible
    const items = screen.getAllByTestId('tool-group-item');
    expect(items).toHaveLength(2);
    expect(screen.getByText('read_file')).toBeTruthy();
    expect(screen.getByText('write_file')).toBeTruthy();
  });

  // 5. shows duration for completed tool (e.g., "2.5s")
  it('shows duration for completed tool', () => {
    const tools: ActiveTool[] = [
      makeTool({
        status: 'complete',
        startedAt: 1000,
        completedAt: 3500,
      }),
    ];
    render(<ToolGroup tools={tools} />);

    expect(screen.getByText('2.5s')).toBeTruthy();
  });

  // 6. shows error text for failed tool
  it('shows error text for failed tool', () => {
    const tools: ActiveTool[] = [
      makeTool({
        status: 'failed',
        error: 'Permission denied: /etc/shadow',
      }),
    ];
    render(<ToolGroup tools={tools} />);

    // Failed icon
    expect(screen.getByText('\u274C')).toBeTruthy();
    // Error text should be visible
    expect(screen.getByText('Permission denied: /etc/shadow')).toBeTruthy();
  });

  // 7. shows output in expandable detail
  it('shows output in expandable detail when toggled', () => {
    const tools: ActiveTool[] = [
      makeTool({
        status: 'complete',
        output: 'file contents here',
      }),
    ];
    render(<ToolGroup tools={tools} />);

    // Output should NOT be visible by default
    expect(screen.queryByText('file contents here')).toBeNull();

    // Click the tool item to expand detail
    fireEvent.click(screen.getByTestId('tool-group-item'));

    // Now output should be visible
    expect(screen.getByText('file contents here')).toBeTruthy();
  });

  // 8. single tool is always expanded (no collapse)
  it('single tool is always expanded with no collapse toggle', () => {
    const tools: ActiveTool[] = [
      makeTool({ status: 'complete', toolName: 'read_file' }),
    ];
    render(<ToolGroup tools={tools} />);

    // Should show the tool item directly (expanded)
    expect(screen.getByTestId('tool-group-item')).toBeTruthy();
    expect(screen.getByText('read_file')).toBeTruthy();
    // Should NOT show the collapsible header summary
    expect(screen.queryByTestId('tool-group-header')).toBeNull();
  });

  // 9. running tool stays visible even when group has completed tools
  it('running tool stays visible even when group has completed tools', () => {
    const tools: ActiveTool[] = [
      makeTool({ toolCallId: 'tc-1', toolName: 'read_file', status: 'complete' }),
      makeTool({ toolCallId: 'tc-2', toolName: 'write_file', status: 'complete' }),
      makeTool({ toolCallId: 'tc-3', toolName: 'bash', status: 'running' }),
    ];
    render(<ToolGroup tools={tools} />);

    // The running tool should be visible
    expect(screen.getByText('bash')).toBeTruthy();
    expect(screen.getByText('\u23F3')).toBeTruthy();
  });
});
