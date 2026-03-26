import { describe, it, expect, beforeEach } from 'vitest';
import {
  getSavedReports,
  saveReport,
  deleteReport,
  getReportById,
  truncateTitle,
  STORAGE_KEY,
} from '../utils/savedReportStorage';
import type { SavedReport } from '../types/swarm';

beforeEach(() => {
  localStorage.clear();
});

describe('savedReportStorage', () => {
  it('getSavedReports returns empty array when nothing stored', () => {
    expect(getSavedReports()).toEqual([]);
  });

  it('saveReport persists a report and getSavedReports retrieves it', () => {
    const report: SavedReport = {
      swarmId: 's1',
      title: 'Test Report',
      timestamp: 1000,
      report: '# Full report markdown',
      phase: 'complete',
    };
    saveReport(report);
    const reports = getSavedReports();
    expect(reports).toHaveLength(1);
    expect(reports[0].swarmId).toBe('s1');
    expect(reports[0].report).toBe('# Full report markdown');
  });

  it('saveReport overwrites existing report with same swarmId (upsert)', () => {
    saveReport({ swarmId: 's1', title: 'V1', timestamp: 1000, report: 'old', phase: 'complete' });
    saveReport({ swarmId: 's1', title: 'V2', timestamp: 2000, report: 'new', phase: 'complete' });
    const reports = getSavedReports();
    expect(reports).toHaveLength(1);
    expect(reports[0].title).toBe('V2');
    expect(reports[0].report).toBe('new');
  });

  it('getSavedReports returns reports sorted by timestamp descending', () => {
    saveReport({ swarmId: 's1', title: 'Old', timestamp: 1000, report: 'r1', phase: 'complete' });
    saveReport({ swarmId: 's2', title: 'New', timestamp: 2000, report: 'r2', phase: 'complete' });
    const reports = getSavedReports();
    expect(reports[0].swarmId).toBe('s2');
    expect(reports[1].swarmId).toBe('s1');
  });

  it('deleteReport removes a report by swarmId', () => {
    saveReport({ swarmId: 's1', title: 'A', timestamp: 1000, report: 'r', phase: 'complete' });
    saveReport({ swarmId: 's2', title: 'B', timestamp: 2000, report: 'r', phase: 'complete' });
    deleteReport('s1');
    const reports = getSavedReports();
    expect(reports).toHaveLength(1);
    expect(reports[0].swarmId).toBe('s2');
  });

  it('deleteReport is no-op for non-existent swarmId', () => {
    saveReport({ swarmId: 's1', title: 'A', timestamp: 1000, report: 'r', phase: 'complete' });
    deleteReport('nonexistent');
    expect(getSavedReports()).toHaveLength(1);
  });

  it('getReportById returns the report or null', () => {
    saveReport({ swarmId: 's1', title: 'A', timestamp: 1000, report: 'r', phase: 'complete' });
    expect(getReportById('s1')?.swarmId).toBe('s1');
    expect(getReportById('missing')).toBeNull();
  });

  it('getSavedReports returns empty array when localStorage contains invalid JSON', () => {
    localStorage.setItem(STORAGE_KEY, 'not-json');
    expect(getSavedReports()).toEqual([]);
  });

  it('caps stored reports at 50, evicting oldest', () => {
    for (let i = 0; i < 55; i++) {
      saveReport({ swarmId: `s${i}`, title: `R${i}`, timestamp: i, report: `r${i}`, phase: 'complete' });
    }
    const reports = getSavedReports();
    expect(reports.length).toBeLessThanOrEqual(50);
    // oldest (s0-s4) should have been evicted
    expect(reports.find((r) => r.swarmId === 's0')).toBeUndefined();
    expect(reports.find((r) => r.swarmId === 's54')).toBeDefined();
  });
});

describe('truncateTitle', () => {
  it('returns full text when under 50 chars', () => {
    expect(truncateTitle('Short title')).toBe('Short title');
  });

  it('truncates at 50 chars and adds ellipsis', () => {
    const long = 'A'.repeat(60);
    const result = truncateTitle(long);
    expect(result).toHaveLength(53); // 50 + '...'
    expect(result.endsWith('...')).toBe(true);
  });

  it('returns "Untitled Report" for empty string', () => {
    expect(truncateTitle('')).toBe('Untitled Report');
  });
});
