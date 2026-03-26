# Warehouse Movement Transaction System

## Context

The current warehouse optimizer is advisory-only — it produces recommendations but has no concept of state, fulfillment, or operational feedback loops. Real warehouse optimization needs to track whether recommendations were actually executed, handle overlapping optimization waves, and react to real-time device data.

## Problem Statement

1. **No fulfillment tracking** — We recommend "move SKU-A from zone 3 to zone 1" but never know if it happened
2. **Overlapping waves** — A second optimization run may recommend moves that conflict with unfulfilled moves from wave 1
3. **No device integration** — Scanners, WMS, and pick systems generate movement data that should feed back into recommendations
4. **Monolithic layout optimizer** — A single agent can't reason about 50 zones simultaneously; needs zonal decomposition

## Proposed Architecture

### Movement Transaction Service

A new backend service (not an agent — a persistent data layer) that tracks movement transactions with credit/debit semantics:

```
Movement Transaction:
  id: uuid
  wave_id: string              # which optimization wave created this
  type: "credit" | "debit"     # credit = add to location, debit = remove from location
  sku: string
  from_zone: string | null     # null for credits (receiving)
  to_zone: string | null       # null for debits (shipping)
  quantity: number
  status: "pending" | "in_progress" | "fulfilled" | "cancelled" | "invalidated"
  created_at: datetime
  fulfilled_at: datetime | null
  invalidated_by: string | null  # wave_id that invalidated this transaction
  device_source: string | null   # device that confirmed fulfillment
```

**Credit/debit pairs:** Every move is two transactions — a debit from source and credit to destination. This allows partial fulfillment tracking and makes the accounting reconcilable.

**Wave management:** Each optimization run creates a wave. When a new wave runs:
1. Check for unfulfilled transactions from previous waves
2. Invalidate conflicting unfulfilled transactions (mark as `invalidated`, reference new wave_id)
3. Create new transactions that account for the actual current state (fulfilled + pending)

### Movement Analyzer Agent

A new agent type that:
- Reads the transaction ledger before making recommendations
- Understands what's been fulfilled vs. pending vs. invalidated
- Factors unfulfilled moves into its analysis (don't re-recommend what's already pending)
- Flags transactions that have been pending too long (stale moves)

### Zonal Layout Agents

Split the monolithic Layout Optimizer into zone-specific agents:
- **Zone Agent** per logical zone (receiving, bulk storage zones A-D, forward pick, packing, shipping)
- Each zone agent optimizes within its zone boundaries
- A **Zone Coordinator** agent resolves cross-zone conflicts (e.g., two zones both want the same SKU in their forward pick area)

Leader decomposes the warehouse into zones and spawns zone agents dynamically based on the facility layout.

### Device Integration

Devices (scanners, WMS webhooks, IoT sensors) feed movement events into the system:

```
Device Event:
  device_id: string
  event_type: "scan" | "pick" | "putaway" | "cycle_count"
  sku: string
  zone: string
  location: string
  quantity: number
  timestamp: datetime
```

Device events:
- Confirm fulfillment of pending transactions (match scan → mark fulfilled)
- Trigger re-analysis when unexpected movements occur
- Invalidate pending transactions when physical state diverges from expected

### Data Flow

```
Devices → Movement Transaction Service → Movement Analyzer
                                              ↓
                                    Zonal Layout Agents
                                              ↓
                                    Implementation Planner
                                              ↓
                                    New Wave of Transactions
                                              ↓
                                    ← Devices confirm fulfillment
```

## Dependencies

- **Persistent storage** — Transactions need a database, not in-memory state. SQLite minimum, Postgres for production.
- **Event stream** — Device events need a real-time ingestion path (WebSocket or message queue)
- **Template system evolution** — Zonal agents are dynamic (count depends on facility), not static template definitions

## Scope Considerations

This is a major feature — not a template tweak. Phases:

1. **Phase 1: Transaction ledger** — Movement Transaction Service with credit/debit, wave tracking, status lifecycle. No devices yet, manual fulfillment marking.
2. **Phase 2: Movement Analyzer agent** — Reads ledger, factors into recommendations, handles wave conflicts.
3. **Phase 3: Zonal decomposition** — Dynamic zone agent spawning, zone coordinator for cross-zone conflicts.
4. **Phase 4: Device integration** — Real-time event ingestion, automatic fulfillment confirmation, invalidation triggers.
