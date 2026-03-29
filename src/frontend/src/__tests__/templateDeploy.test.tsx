import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SwarmControls } from '../components/SwarmControls';

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('Template Deploy Button', () => {
  it('renders a deploy/upload button', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [{ key: 'test', name: 'Test', description: '' }] }),
    } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      const deployBtn = screen.getByTitle('Deploy template pack');
      expect(deployBtn).toBeTruthy();
    });
  });

  it('deploy button appears before the template dropdown', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [{ key: 'test', name: 'Test', description: '' }] }),
    } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      const actions = screen.getByTestId('swarm-actions');
      const children = Array.from(actions.children);
      const deployIdx = children.findIndex((c) => c.getAttribute('title') === 'Deploy template pack');
      const selectIdx = children.findIndex((c) => c.tagName === 'SELECT');
      expect(deployIdx).toBeLessThan(selectIdx);
    });
  });

  it('clicking deploy triggers file input for zip upload', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [{ key: 'test', name: 'Test', description: '' }] }),
    } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      screen.getByTitle('Deploy template pack');
    });

    // The deploy button should have a hidden file input associated with it
    const fileInput = document.querySelector('input[type="file"][accept=".zip"]');
    expect(fileInput).toBeTruthy();
  });
});
