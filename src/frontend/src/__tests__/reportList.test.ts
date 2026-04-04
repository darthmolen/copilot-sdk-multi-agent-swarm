import { describe, it, expect } from 'vitest';
import { buildReportList } from '../utils/buildReportList';
import type { SwarmState, SavedReport } from '../types/swarm';

const baseSwarm: SwarmState = {
  phase: null,
  tasks: [],
  agents: [],
  messages: [],
  leaderPlan: '',
  leaderReport: '',
  agentOutputs: {},
  activeTools: [],
  roundNumber: 0,
  error: null,
};

describe('buildReportList', () => {
  it('returns generating status for synthesizing swarm with report content', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'synthesizing', leaderReport: '# Partial report' },
    };
    const result = buildReportList(['s1'], [], swarms, []);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('generating');
    expect(result[0].swarmId).toBe('s1');
  });

  it('returns live status for completed swarm with report', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'complete', leaderReport: '# Done' },
    };
    const result = buildReportList([], ['s1'], swarms, []);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('live');
  });

  it('returns saved status for localStorage-only report', () => {
    const saved: SavedReport[] = [{
      swarmId: 'old-1',
      title: 'Old Report',
      timestamp: 1000,
      report: '# Old',
      phase: 'complete',
    }];
    const result = buildReportList([], [], {}, saved);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('saved');
  });

  it('deduplicates: live report is not duplicated with saved version', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'complete', leaderReport: '# Done' },
    };
    const saved: SavedReport[] = [{
      swarmId: 's1',
      title: 'Same report',
      timestamp: 1000,
      report: '# Done',
      phase: 'complete',
    }];
    const result = buildReportList([], ['s1'], swarms, saved);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('live');
  });

  it('sorts by timestamp descending (newest first)', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'complete', leaderReport: '# Old' },
      's2': { ...baseSwarm, phase: 'complete', leaderReport: '# New' },
    };
    const saved: SavedReport[] = [
      { swarmId: 's1', title: 'Old', timestamp: 1000, report: '#', phase: 'complete' },
      { swarmId: 's2', title: 'New', timestamp: 2000, report: '#', phase: 'complete' },
    ];
    const result = buildReportList([], ['s1', 's2'], swarms, saved);
    expect(result[0].swarmId).toBe('s2');
    expect(result[1].swarmId).toBe('s1');
  });

  it('generating items sort before live items', () => {
    const swarms: Record<string, SwarmState> = {
      'gen': { ...baseSwarm, phase: 'synthesizing', leaderReport: '# Generating...' },
      'done': { ...baseSwarm, phase: 'complete', leaderReport: '# Done' },
    };
    const result = buildReportList(['gen'], ['done'], swarms, []);
    expect(result[0].status).toBe('generating');
    expect(result[1].status).toBe('live');
  });

  it('includes active swarm in executing phase as running', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'executing', leaderReport: '' },
    };
    const result = buildReportList(['s1'], [], swarms, []);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('running');
    expect(result[0].swarmId).toBe('s1');
  });

  it('includes active swarm in qa phase as running', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'qa', leaderReport: '' },
    };
    const result = buildReportList(['s1'], [], swarms, []);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('running');
  });

  it('includes active swarm in planning phase as running', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'planning', leaderReport: '' },
    };
    const result = buildReportList(['s1'], [], swarms, []);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe('running');
  });

  it('running items sort before live and saved', () => {
    const swarms: Record<string, SwarmState> = {
      'run': { ...baseSwarm, phase: 'executing', leaderReport: '' },
      'done': { ...baseSwarm, phase: 'complete', leaderReport: '# Done' },
    };
    const result = buildReportList(['run'], ['done'], swarms, []);
    expect(result[0].status).toBe('running');
    expect(result[1].status).toBe('live');
  });

  it('running swarm title includes truncated swarm ID', () => {
    const swarms: Record<string, SwarmState> = {
      'abcdef12-3456-7890': { ...baseSwarm, phase: 'executing', leaderReport: '' },
    };
    const result = buildReportList(['abcdef12-3456-7890'], [], swarms, []);
    expect(result[0].title).toContain('abcdef12');
  });

  it('extracts title from first heading line of report', () => {
    const swarms: Record<string, SwarmState> = {
      's1': { ...baseSwarm, phase: 'complete', leaderReport: '# My Great Report\n\nBody text' },
    };
    const result = buildReportList([], ['s1'], swarms, []);
    expect(result[0].title).toBe('My Great Report');
  });
});
