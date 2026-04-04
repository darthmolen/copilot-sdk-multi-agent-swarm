# COMPLETED: PostgreSQL Persistence Layer

Completed 2026-04-04. Merged in PR #8.

## What Was Built

- **SwarmService** — single source of truth. Cache-first reads (TaskBoard/InboxSystem/TeamRegistry), write-through to Postgres when `DATABASE_URL` is set
- **SwarmRepository** — pure data access layer. 6 tables: swarms, tasks, agents, messages, events, files
- **EventLogger** — EventBus subscriber for append-only event log
- **Per-test DB isolation** — each integration test gets its own `test_{uuid}` Postgres database with real Alembic migrations
- **Agent session_id capture** — stored for future recovery feature
- **API endpoints** — `GET /api/swarm/{id}/events` (event replay), `GET /api/swarms` (historical list)
- **Docker Compose** — Postgres 17 with healthcheck

## Architecture Decision

Service layer pattern instead of direct repository injection. The orchestrator calls `SwarmService` — one interface, no scattered `if repo:` guards. Cache impl is swappable (Redis later) without touching orchestrator.

## Tables

swarms, tasks, agents, messages, events (append-only), files

## Tests

310 unit + 24 integration = 334 total
