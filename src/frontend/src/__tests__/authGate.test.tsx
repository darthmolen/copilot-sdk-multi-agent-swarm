import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock components that break in jsdom
vi.mock('../components/SwarmControls', () => ({
  SwarmControls: () => <div data-testid="swarm-controls">SwarmControls</div>,
}));

vi.mock('../components/InboxFeed', () => ({
  InboxFeed: () => <div>InboxFeed</div>,
}));

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: () => {},
}));

vi.mock('../hooks/useMermaid', () => ({
  useMermaid: () => {},
}));

// Import App after mocks are set up
import App from '../App';

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe('AuthGate', () => {
  it('skips auth gate when backend does not require auth (200 on probe)', async () => {
    // Backend returns 200 without auth — dev mode, no key configured
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [] }),
    } as Response);

    render(<App />);

    // Should NOT show the auth gate — should show the dashboard
    await waitFor(() => {
      expect(screen.queryByText('Enter your API key to continue')).toBeNull();
    });
  });

  it('shows auth gate when backend requires auth (401 on probe)', async () => {
    // Backend returns 401 — auth is required
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Invalid API key' }),
    } as Response);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Enter your API key to continue')).toBeTruthy();
    });
  });

  it('skips auth gate when key already in sessionStorage', async () => {
    sessionStorage.setItem('swarm_api_key', 'test-key');

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [] }),
    } as Response);

    render(<App />);

    await waitFor(() => {
      expect(screen.queryByText('Enter your API key to continue')).toBeNull();
    });
  });
});
