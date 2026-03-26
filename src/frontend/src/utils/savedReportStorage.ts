import type { SavedReport } from '../types/swarm';

export const STORAGE_KEY = 'swarm_saved_reports';
const MAX_REPORTS = 50;

export function getSavedReports(): SavedReport[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.sort((a: SavedReport, b: SavedReport) => b.timestamp - a.timestamp);
  } catch {
    return [];
  }
}

export function saveReport(report: SavedReport): void {
  const reports = getSavedReports().filter((r) => r.swarmId !== report.swarmId);
  reports.push(report);
  reports.sort((a, b) => b.timestamp - a.timestamp);
  const capped = reports.slice(0, MAX_REPORTS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
}

export function deleteReport(swarmId: string): void {
  const reports = getSavedReports().filter((r) => r.swarmId !== swarmId);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(reports));
}

export function getReportById(swarmId: string): SavedReport | null {
  return getSavedReports().find((r) => r.swarmId === swarmId) ?? null;
}

export function truncateTitle(text: string, maxLen = 50): string {
  if (!text) return 'Untitled Report';
  return text.length <= maxLen ? text : text.slice(0, maxLen) + '...';
}
