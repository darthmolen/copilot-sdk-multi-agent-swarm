import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { SwarmControls } from '../components/SwarmControls';

const mockTemplates = [
  { key: 'deep-research', name: 'Deep Research Team', description: 'Research team' },
  { key: 'warehouse-optimizer', name: 'Warehouse Optimization Team', description: 'Warehouse team' },
];

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('SwarmControls', () => {
  it('fetches templates from API on mount', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => ({ templates: mockTemplates }),
    } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/templates'),
        expect.any(Object),
      );
    });
  });

  it('renders fetched templates in the dropdown', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => ({ templates: mockTemplates }),
    } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      const options = screen.getAllByRole('option');
      const labels = options.map((o) => o.textContent);
      expect(labels).toContain('Deep Research Team');
      expect(labels).toContain('Warehouse Optimization Team');
    });
  });

  it('does not use a hardcoded template list', async () => {
    // If fetch fails, should show empty or loading — NOT hardcoded templates
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('Network error'));

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      const options = screen.queryAllByRole('option');
      // Should either be empty or have a placeholder — not hardcoded values
      const labels = options.map((o) => o.textContent);
      expect(labels).not.toContain('Deep Research');
      expect(labels).not.toContain('Warehouse Optimizer');
    });
  });
});
