import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import toast from 'react-hot-toast';
import { SwarmControls } from '../components/SwarmControls';

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe('Toast Notifications', () => {
  it('deploy success shows a toast notification', async () => {
    const toastSpy = vi.spyOn(toast, 'success');

    const templates = [{ key: 'test', name: 'Test', description: '' }];
    vi.spyOn(globalThis, 'fetch')
      // SwarmControls template fetch on mount
      .mockResolvedValueOnce({ ok: true, json: async () => ({ templates }) } as Response)
      // deploy POST
      .mockResolvedValueOnce({ ok: true, json: async () => ({ key: 'deployed', name: 'Deployed Template', description: '' }) } as Response)
      // post-deploy template refresh
      .mockResolvedValueOnce({ ok: true, json: async () => ({ templates }) } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTitle('Deploy template pack')).toBeTruthy();
    });

    const fileInput = document.querySelector('input[type="file"][accept=".zip"]') as HTMLInputElement;
    const file = new File(['fake-zip-content'], 'test.zip', { type: 'application/zip' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('Deployed Template'));
    });
  });

  it('deploy failure shows an error toast', async () => {
    const toastSpy = vi.spyOn(toast, 'error');

    const templates = [{ key: 'test', name: 'Test', description: '' }];
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({ ok: true, json: async () => ({ templates }) } as Response)
      .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ detail: 'Zip must contain _template.yaml' }) } as Response);

    render(<SwarmControls onStart={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTitle('Deploy template pack')).toBeTruthy();
    });

    const fileInput = document.querySelector('input[type="file"][accept=".zip"]') as HTMLInputElement;
    const file = new File(['bad-zip'], 'bad.zip', { type: 'application/zip' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('_template.yaml'));
    });
  });
});
