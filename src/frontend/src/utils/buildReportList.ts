import type { SavedReport, SwarmState } from '../types/swarm';
import { truncateTitle } from './savedReportStorage';

export interface SuspendedSwarm {
  id: string;
  goal: string;
  template_key: string | null;
  current_round: number;
  max_rounds: number;
  created_at: string;
}

export type ReportStatus = 'running' | 'generating' | 'live' | 'saved' | 'suspended';

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
  suspendedSwarms: SuspendedSwarm[] = [],
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

  // Suspended swarms from DB (not already in the live/saved set)
  for (const sw of suspendedSwarms) {
    if (!seenIds.has(sw.id)) {
      const goalLine = sw.goal.split('\n').find((l) => l.trim() && !l.startsWith('#'))?.trim() ?? '';
      items.push({
        swarmId: sw.id,
        title: truncateTitle(goalLine || `Suspended ${sw.id.slice(0, 8)}...`),
        timestamp: new Date(sw.created_at).getTime(),
        status: 'suspended',
      });
      seenIds.add(sw.id);
    }
  }

  // Sort: running/generating first, suspended next, then saved/live
  const priority = (s: ReportStatus) => {
    if (s === 'running' || s === 'generating') return 0;
    if (s === 'suspended') return 1;
    return 2;
  };
  items.sort((a, b) => {
    const pa = priority(a.status);
    const pb = priority(b.status);
    if (pa !== pb) return pa - pb;
    return b.timestamp - a.timestamp;
  });

  return items;
}
