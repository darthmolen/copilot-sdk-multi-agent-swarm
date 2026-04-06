# MCP Swarm Server

## Overview

The swarm system exposes an in-process MCP server at `/mcp` on the FastAPI app. This turns the swarm from a dashboard application into a **composable component in any agentic ecosystem** — any MCP client (Claude Code, Copilot, another agent, an IDE extension) can discover templates, launch swarms, monitor progress, and retrieve results programmatically.

The server is built with FastMCP and uses streamable HTTP transport. Auth is handled via `X-API-Key` header at the ASGI layer, invisible to the agent context.

## Agentic Use Cases

Because the MCP server exposes the full swarm lifecycle, external agents can orchestrate swarms as a capability — the same way they'd call a search API or a database. The use cases are only constrained by the imagination of the templates:

**Research automation:** A planning agent identifies knowledge gaps, calls `get_swarm_templates` to find the deep-research template, launches a swarm with `create_swarm`, polls `get_swarm_summary` until complete, then reads the synthesis report via `read_artifact` and incorporates findings into its own work.

**Infrastructure-as-Code pipelines:** A DevOps agent receives a deployment request, launches an Azure solutions swarm to generate Bicep modules, monitors task progress, and upon completion pulls the generated artifacts for deployment.

**Multi-swarm orchestration:** A meta-agent decomposes a large initiative into several swarms — one for architecture design, one for security review, one for implementation — launches them in parallel via `create_swarm`, monitors all three with `get_swarm_summary`, and synthesizes the results.

**Quality gates:** A CI/CD agent launches a code review swarm after a PR is created, waits for completion, reads the report, and posts findings as PR comments.

**Self-improving agents:** An agent that encounters a complex problem beyond its scope launches a specialized swarm (e.g., deep-research) to investigate, then uses the results to continue its own task.

## Tools

### Swarm Lifecycle

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_swarm_templates` | (none) | List available templates with key, name, and description. Use to discover what swarm types are available before creating one. |
| `create_swarm` | `goal`, `template?` | Start a new swarm. Returns `swarm_id` for monitoring. Optional `template` must match a key from `get_swarm_templates`. |
| `get_swarm_summary` | `swarm_id` | Token-efficient status check. Returns `status` plus context-dependent fields: `report` + `artifact_path` when complete, `task_progress` when running, `error` when failed/suspended. The `artifact_path` value can be passed directly to `read_artifact`. |

### Swarm Inspection

| Tool | Parameters | Description |
| --- | --- | --- |
| `get_active_swarms` | (none) | List all swarms with ID, phase, goal, and template. No `swarm_id` required. |
| `get_swarm_status` | `swarm_id` | Detailed status: phase, round number, agent count, task counts by status. |
| `list_tasks` | `swarm_id`, `status?`, `worker?` | All tasks with optional filters. Returns subject, status, worker, result. |
| `get_task_detail` | `swarm_id`, `task_id` | Full task detail including description and result text. |
| `list_agents` | `swarm_id` | Agent roster with role, status, and tasks completed count. |
| `get_recent_events` | `swarm_id`, `count?`, `since?` | Event history from Postgres. Useful for debugging or auditing. |

### Artifact Access

| Tool | Parameters | Description |
| --- | --- | --- |
| `list_artifacts` | `swarm_id` | Files in the swarm's work directory with names, paths, and sizes. |
| `read_artifact` | `swarm_id`, `path` | Read a specific file. Path is relative to the swarm directory. Protected against path traversal. |

### Agent Management

| Tool | Parameters | Description |
| --- | --- | --- |
| `resume_agent` | `swarm_id`, `agent_name`, `nudge?` | Resume a failed agent's session with full conversation history preserved. Optional nudge message guides the agent toward a different approach. |

## Typical Agent Flow

```
1. get_swarm_templates()
   → [{"key": "azure-solutions", "name": "Azure Solutions Architect", ...}, ...]

2. create_swarm(goal="Design AKS platform for 50 microservices", template="azure-solutions")
   → {"swarm_id": "abc-123", "status": "starting"}

3. get_swarm_summary(swarm_id="abc-123")   // poll periodically
   → {"status": "executing", "task_progress": "4/11 completed"}

4. get_swarm_summary(swarm_id="abc-123")   // later
   → {"status": "complete", "report": "# Azure Container Platform...", "artifact_path": "synthesis_report.md"}

5. list_artifacts(swarm_id="abc-123")      // optional: see all generated files
   → [{"name": "main.bicep", ...}, {"name": "aks.bicep", ...}, ...]

6. read_artifact(swarm_id="abc-123", path="main.bicep")
   → {"content": "targetScope = 'subscription'\n..."}
```

## Multi-Swarm Isolation

All tools except `get_active_swarms` and `get_swarm_templates` require `swarm_id`. Each swarm has isolated state — tasks, agents, artifacts, and events are scoped to their swarm. Multiple swarms run concurrently without interference.

## Configuration

The MCP server is configured during app startup in `main.py`. Dependencies injected:

- `swarm_store` — in-memory swarm state (cache, backfilled from Postgres)
- `work_dir` — base directory for swarm artifacts
- `event_bus` — event publisher for real-time updates
- `repository` — Postgres repository for persistence
- `template_loader` — template discovery and loading
- `start_swarm` — async callable to create and launch a swarm
