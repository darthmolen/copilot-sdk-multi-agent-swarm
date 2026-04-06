import type { MultiSwarmAction } from '../hooks/useSwarmState';
import type { Task } from '../types/swarm';

/**
 * Build reducer actions that hydrate tasks from a /status response
 * into the multi-swarm store. Each task becomes a task.created event
 * dispatched to the given swarmId.
 *
 * The caller is responsible for guarding against duplicate hydration
 * (e.g. checking `store.swarms[id]?.tasks?.length` before calling).
 */
export function hydrateTasksIntoSwarm(
  swarmId: string,
  tasks: Task[] | undefined | null,
): MultiSwarmAction[] {
  if (!tasks || tasks.length === 0) return [];

  return tasks.map((task) => ({
    type: 'swarm.event' as const,
    swarmId,
    event: {
      type: 'task.created',
      data: { task, swarm_id: swarmId },
    },
  }));
}
