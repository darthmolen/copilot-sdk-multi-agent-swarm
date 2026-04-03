import type { SwarmState, SavedReport } from '../types/swarm';
import { truncateTitle } from './savedReportStorage';

export type ReportStatus = 'running' | 'generating' | 'live' | 'saved';

export interface ReportListItem {
  swarmId: string;
  title: string;
  timestamp: number;
  status: ReportStatus;
}

export function buildReportList(
  activeSwarmIds: string[],
  completedSwarmIds: string[],
  swarms: Record<string, SwarmState>,
  savedReports: SavedReport[],
): ReportListItem[] {
  const items: ReportListItem[] = [];
  const seenIds = new Set<string>();

  // Active swarms: synthesizing with report → 'generating', all others → 'running'
  for (const id of activeSwarmIds) {
    const swarm = swarms[id];
    if (!swarm) continue;
    if (swarm.leaderReport && swarm.phase === 'synthesizing') {
      const firstLine = swarm.leaderReport.split('\n')[0].replace(/^#+\s*/, '');
      items.push({
        swarmId: id,
        title: truncateTitle(firstLine),
        timestamp: Date.now(),
        status: 'generating',
      });
    } else {
      items.push({
        swarmId: id,
        title: `Session ${id.slice(0, 8)}...`,
        timestamp: Date.now(),
        status: 'running',
      });
    }
    seenIds.add(id);
  }

  // Completed swarms with reports
  for (const id of completedSwarmIds) {
    const swarm = swarms[id];
    if (swarm?.leaderReport) {
      const firstLine = swarm.leaderReport.split('\n')[0].replace(/^#+\s*/, '');
      // Use saved timestamp if available, otherwise now
      const saved = savedReports.find((r) => r.swarmId === id);
      items.push({
        swarmId: id,
        title: truncateTitle(firstLine),
        timestamp: saved?.timestamp ?? Date.now(),
        status: 'live',
      });
      seenIds.add(id);
    }
  }

  // Saved reports not already in the live set
  for (const r of savedReports) {
    if (!seenIds.has(r.swarmId)) {
      items.push({
        swarmId: r.swarmId,
        title: r.title,
        timestamp: r.timestamp,
        status: 'saved',
      });
    }
  }

  // Sort: running/generating first, then by timestamp descending
  const priority = (s: ReportStatus) => (s === 'running' || s === 'generating') ? 0 : 1;
  items.sort((a, b) => {
    const pa = priority(a.status);
    const pb = priority(b.status);
    if (pa !== pb) return pa - pb;
    return b.timestamp - a.timestamp;
  });

  return items;
}
