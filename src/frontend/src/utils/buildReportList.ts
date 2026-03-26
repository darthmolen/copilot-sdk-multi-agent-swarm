import type { SwarmState, SavedReport } from '../types/swarm';
import { truncateTitle } from './savedReportStorage';

export type ReportStatus = 'generating' | 'live' | 'saved';

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

  // Active swarms that are synthesizing with partial report
  for (const id of activeSwarmIds) {
    const swarm = swarms[id];
    if (swarm?.leaderReport && swarm.phase === 'synthesizing') {
      const firstLine = swarm.leaderReport.split('\n')[0].replace(/^#+\s*/, '');
      items.push({
        swarmId: id,
        title: truncateTitle(firstLine),
        timestamp: Date.now(),
        status: 'generating',
      });
      seenIds.add(id);
    }
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

  // Sort: generating first, then by timestamp descending
  items.sort((a, b) => {
    if (a.status === 'generating' && b.status !== 'generating') return -1;
    if (b.status === 'generating' && a.status !== 'generating') return 1;
    return b.timestamp - a.timestamp;
  });

  return items;
}
