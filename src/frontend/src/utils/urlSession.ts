const PARAM_NAMES = ['session', 'session_id', 'swarm_id'] as const;

export function parseSessionFromSearch(search: string): string | null {
  const params = new URLSearchParams(search);
  for (const name of PARAM_NAMES) {
    const value = params.get(name);
    if (value) return value;
  }
  return null;
}

export function buildSessionUrl(swarmId: string): string {
  return `${window.location.pathname}?session=${encodeURIComponent(swarmId)}`;
}
