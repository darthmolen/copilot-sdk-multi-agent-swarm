import { describe, it, expect } from 'vitest';
import { parseSessionFromSearch, buildSessionUrl } from '../utils/urlSession';

describe('parseSessionFromSearch', () => {
  it('returns swarmId from ?session=abc-123', () => {
    expect(parseSessionFromSearch('?session=abc-123')).toBe('abc-123');
  });

  it('returns swarmId from ?session_id=abc-123', () => {
    expect(parseSessionFromSearch('?session_id=abc-123')).toBe('abc-123');
  });

  it('returns swarmId from ?swarm_id=abc-123', () => {
    expect(parseSessionFromSearch('?swarm_id=abc-123')).toBe('abc-123');
  });

  it('prefers session over session_id over swarm_id', () => {
    expect(parseSessionFromSearch('?session=a&session_id=b&swarm_id=c')).toBe('a');
    expect(parseSessionFromSearch('?session_id=b&swarm_id=c')).toBe('b');
  });

  it('returns null when no matching param', () => {
    expect(parseSessionFromSearch('')).toBeNull();
    expect(parseSessionFromSearch('?foo=bar')).toBeNull();
  });

  it('returns null for empty value', () => {
    expect(parseSessionFromSearch('?session=')).toBeNull();
  });

  it('handles param among other params', () => {
    expect(parseSessionFromSearch('?mode=dark&session=xyz&lang=en')).toBe('xyz');
  });
});

describe('buildSessionUrl', () => {
  it('includes the session query param', () => {
    const url = buildSessionUrl('swarm-abc');
    expect(url).toContain('?session=swarm-abc');
  });
});
