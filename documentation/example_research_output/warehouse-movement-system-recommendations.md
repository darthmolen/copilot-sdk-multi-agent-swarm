# Warehouse Movement Transaction System (WMTS)
## Deep Research Synthesis Report

**Date:** 2026-03-26 | **Prepared by:** Lead Synthesis Analyst
**Research Team:** Dr. Priya Nair (Primary), Marcus Webb (Skeptic), Sofia Reyes (Data/Quantitative)

---

## Executive Summary

A production-ready Warehouse Movement Transaction System for a Dell Global Parts Depot is architecturally sound in concept but carries several critical design gaps that — if unaddressed — will cause inventory drift, operational halts, and corrupted data under real-world warehouse load. The credit/debit ledger model is the right primitive, validated by mature enterprise WMS patterns (Dynamics 365, SAP EWM), but the proposed design is missing an explicit **in-transit state**, lacks **task-locking to prevent mid-execution invalidation**, and underspecifies **scan matching semantics** for concurrent identical moves. Two findings warrant immediate design intervention before any code is written: the Wave Invalidation Race Condition (RISK-002) and the SQL latch contention problem under high write/read concurrency (RISK-004). Dell's serialized-unit workflows (firmware reflash, RMA triage, SKU identity transformation) add substantial complexity that standard WMS literature does not cover and requires bespoke data modelling. The phased rollout strategy — Shadow Ledger → Active Pilot → Full Control — is validated across all three research tracks and should be treated as non-negotiable sequencing.

---

## Key Findings

### 1. The Ledger-Based Transaction Model Is Correct, But Incomplete
**Evidence Quality:** Strong
**Source:** D365 `InventTrans` pattern; SAP EWM transaction architecture; Dr. Nair primary research

The use of append-only transaction rows (rather than mutable quantity fields) is the established standard in every mature WMS. D365 models every inventory movement as a discrete row with a status-based state machine; the "balance" at any location is always computed as a `SUM()` over valid transaction rows — never a counter. The proposed architecture correctly adopts this pattern.

**Critical Gap:** The proposed status lifecycle (`pending → in_progress → fulfilled → cancelled → invalidated`) is missing a dedicated **`in_transit`** state between a Debit (pick from source) and its corresponding Credit (putaway at destination). Without this, there is a temporal window — potentially hours long if a worker pauses — where stock is physically in motion but appears to have vanished from the ledger. This is not a minor omission; it is a correctness invariant the entire system depends on.

**Required Addition to Schema:**
```
status: "planned" | "assigned" | "in_transit" | "fulfilled" | "cancelled" | "invalidated"
```
The Debit half of a move transitions to `in_transit` at the moment of the physical pick scan. It becomes `fulfilled` only when the Credit (putaway) scan is confirmed.

---

### 2. Wave Management Requires Hard Task-Locking
**Evidence Quality:** Strong
**Source:** D365 Wave Processing Docs (allocation hard-lock semantics); Webb Risk Register RISK-002

The most dangerous design assumption in the proposal is that unfulfilled transactions from Wave N can be freely invalidated when Wave N+1 runs. In practice, a worker may be physically *mid-execution* of a task when the system attempts to invalidate it. D365 addresses this with a hard allocation step: once work is released to the floor, it is **frozen** — no subsequent wave can touch it until it completes or is explicitly recalled through a supervisor flow.

**Required Rule:** Any transaction in `assigned` or `in_transit` status **must be immune to wave invalidation**. The Wave Engine must query for and respect these locks before planning. This means the wave conflict resolution algorithm needs a two-pass design:
- **Pass 1:** Identify truly unstarted (`planned`) conflicting transactions → safe to invalidate.
- **Pass 2:** Route around `assigned`/`in_transit` transactions → treat their in-progress moves as committed facts.

---

### 3. Scan Matching by SKU/Zone Is Insufficient; Transaction IDs Required
**Evidence Quality:** Strong
**Source:** Webb RISK-003; D365 Mobile App Protocol (server-side session state)

The proposal relies on matching a device event `(SKU, Zone, Location)` to an open transaction. This fails immediately in any scenario with two concurrent moves of the same SKU from the same zone (e.g., two pickers fulfilling two orders for `SKU-X` from Zone A to Zone B simultaneously). The system cannot disambiguate which physical pick corresponds to which transaction record.

**Industry Standard:** The `Transaction UUID` must be embedded in every work instruction issued to a scanner. D365 achieves this via a `WMSWorkID` on every pick task. The scanner app encodes and returns the work ID on confirmation, making matching deterministic and unambiguous. Physical pick lists, scanner task screens, and barcode labels for directed putaways must all carry the UUID.

---

### 4. SQL Server CQRS Separation Is Non-Negotiable Under Warehouse Load
**Evidence Quality:** Strong
**Source:** Webb RISK-004; Sofia Reyes volumetric analysis; standard CQRS pattern

A single SQL Server table serving as both the high-frequency write target (scanner events, ~50 concurrent workers at shift start) and the analytical read source (Wave Engine running `SUM()` aggregations across tens of thousands of rows) will produce latch contention and deadlocks. This is not a hypothetical — it is a predictable outcome given the access patterns.

**Required Architecture:** Full CQRS separation:
- **Write side:** `MovementTransactions` table, write-optimized, minimal indexes, EF Core.
- **Read side:** A separate **read replica** (SQL Server Transactional Replication or Always On readable secondary) or a materialized **OLAP projection table** refreshed via a background service. The Wave Engine and Movement Analyzer Agent **only touch the read side**.

At the estimated transaction volume for a global parts depot (see Data Insights), this separation is not premature optimization — it is a baseline correctness requirement.

---

### 5. Dell's Serialized/Reflash Workflows Require SKU Identity Change Modelling
**Evidence Quality:** Strong
**Source:** Dr. Nair Dell-specific analysis; Webb RISK-007

Standard WMS literature assumes **SKU identity is immutable** across a transaction's lifecycle. Dell's reflash workflow violates this at a fundamental level: a unit enters the reflash zone as `SKU-123 (FW v1.2)` and exits as `SKU-456 (FW v2.0)`. In a naive credit/debit model, the Debit of `SKU-123` is permanently unmatched, and the Credit of `SKU-456` has no originating transaction. The ledger drifts by -1/+1 per unit reflashed, compounding permanently.

**Required Design:** Introduce a **`WorkOrder` entity** that wraps reflash and repair operations:
```
WorkOrder:
  id: uuid
  type: "reflash" | "repair" | "rma_triage"
  input_unit_id: string        # serial number
  input_sku: string
  output_unit_id: string       # may be same serial
  output_sku: string           # may differ (firmware version change)
  firmware_version_target: string | null
  status: "queued" | "in_progress" | "completed" | "failed"
  failure_reason: string | null
```
The Debit of `SKU-123` closes against the `WorkOrder`, not against a Credit of `SKU-123`. The Credit of `SKU-456` opens as a new inventory entry linked to the `WorkOrder`. The ledger remains balanced through the work order join, not through direct transaction pairing.

---

### 6. Legacy WMS Observability Must Use CDC, Not Direct Queries
**Evidence Quality:** Strong
**Source:** Dr. Nair (Debezium/SQL Server CDC); Synthesis Report Section 7; Webb RISK-006

Extracting observability data from the opaque custom WMS by directly querying its operational tables is dangerous. Even with `NOLOCK` hints, high-frequency polling adds measurable read I/O to a system that cannot tolerate it. More critically, writing back to the WMS SQL tables directly (without an API contract) is the highest-risk integration approach available and should be prohibited by policy.

**Recommended Stack:**
1. **Enable CDC** on the WMS SQL Server database (requires `db_owner` or sysadmin permission negotiation with IT).
2. **Stream changes** via Debezium → RabbitMQ or Azure Service Bus.
3. **Transform** raw CDC row events into semantic domain events (`InventoryMoved`, `OrderShipped`) in a lightweight .NET transformer service.
4. **Consume** in the WMTS Shadow Ledger for Phase 1 reconciliation.

If CDC is blocked by the database team, the fallback is a **polling service** on a `ModifiedDateTime` high-water mark with `READ UNCOMMITTED` — acceptable for the Shadow phase but explicitly unsuitable for production control.

---

## Evidence Analysis

### Areas of Strong Convergence

| Claim | Primary Research | Skeptic | Data Analysis | Convergence |
|:---|:---:|:---:|:---:|:---:|
| Ledger model is correct pattern | ✅ Validated | ✅ Supports (with in-transit gap) | ✅ Industry standard | **Strong** |
| Wave invalidation needs task locking | ✅ D365 precedent | ✅ RISK-002 Critical | ✅ Race condition math | **Strong** |
| CQRS separation required at scale | Mentioned | ✅ RISK-004 Critical | ✅ Volume confirms | **Strong** |
| CDC for WMS extraction | ✅ Recommended | ✅ RISK-006 High | ✅ Safer than polling | **Strong** |
| Serial tracking non-negotiable for Dell | ✅ Explicit | ✅ RISK-007 | — | **Strong** |
| Offline-first mobile design required | ✅ D365 dumb terminal | ✅ Dead zone scenarios | ✅ Connectivity math | **Strong** |

### Areas of Contradictory or Insufficient Evidence

| Area | Gap | Impact |
|:---|:---|:---:|
| **Reflash station automation** | Unknown whether stations can push MQTT/HTTP directly or require manual scan. Architecture differs significantly between paths. | High |
| **WMS write-back API existence** | Unknown if legacy WMS exposes any API vs. raw SQL tables. This determines Phase 2 integration strategy entirely. | Critical |
| **Device hardware specs** | Zebra/Honeywell vs. iPad determines mobile framework (MAUI vs. Blazor Hybrid vs. web). Not yet known. | Medium |
| **WMS schema legibility** | The "opaque" WMS may use cryptic column names, triggers, or stored procedure business logic. CDC captures raw table changes; semantic meaning requires reverse-engineering. | High |
| **Actual transaction volume** | Sofia Reyes's volumetric model uses industry estimates, not Dell-specific throughput numbers. Peak load assumptions may be significantly off. | Medium |

### Most Reliable Data Points
- The ledger/transaction model architecture (validated by two mature enterprise systems)
- CQRS necessity given mixed read/write workloads
- The in-transit state gap (logical deduction from the schema, not empirical)

### Most Uncertain Estimates
- Peak transaction throughput (requires actual WMS instrumentation data)
- Phase duration estimates (depend heavily on WMS schema complexity, which is unknown)

---

## Contrarian Perspectives

Marcus Webb's skeptical analysis identified **2 Critical, 3 High, and 3 Medium risks**. The most significant challenges to the primary design follow:

### Challenge 1: The "In-Transit Black Hole" Is a Correctness Invariant Failure
Webb identifies that the credit/debit abstraction, while accounting-friendly, is **too low-level** to model the physical reality of goods in motion. The scenario of a picker going to lunch with a pallet is not edge-case speculation — it happens on every shift. The absence of a first-class in-transit state means the system will routinely show phantom stock deficits, which will trigger erroneous re-order recommendations from the Wave Engine.

**Effect on Primary Findings:** Partially modifies Finding #1. The ledger model is still correct, but the proposed status lifecycle requires a mandatory revision before implementation begins. This is not a Phase 2 concern; it must be in the Phase 1 schema.

### Challenge 2: Wave Invalidation Is More Dangerous Than Presented
The proposal presents wave invalidation as a clean algorithmic step. Webb's analysis correctly frames it as a **UX and operational safety problem as much as a technical one**: when a transaction is invalidated mid-execution, the worker holds physical inventory with no valid system state. Without a defined "Rollback Instruction" workflow (e.g., scanner showing "Put item back at Bin A-14"), the physical and digital states diverge immediately and irrecoverably.

**Effect on Primary Findings:** Adds a required UX flow not present in the original architecture. The invalidation mechanism needs a worker notification path and a `rollback_instruction` field on the transaction record.

### Challenge 3: The Zone Coordinator Is a Hidden Single Point of Failure
The proposal's Zone Coordinator resolves cross-zone conflicts but is described without any redundancy, failover, or throughput bound. As zone count grows (and a global depot could have dozens of logical zones), the Coordinator processes conflicts serially and becomes the throughput ceiling for the entire wave planning process.

**Effect on Primary Findings:** The Zonal Decomposition architecture (Phase 3) needs a redesigned Coordinator that uses a **distributed lock or consensus mechanism** (e.g., Redlock pattern, or simply a conflict-resolution queue with parallel processing of non-conflicting zone pairs) rather than a single sequential arbiter.

### Challenge 4: CDC Is Not "Free" Observability
While CDC is the correct recommendation, Webb correctly flags that enabling it on a high-volume legacy system can spike transaction log usage and degrade the very system being observed. The "observer effect" risk is real.

**Effect on Primary Findings:** CDC enablement must be preceded by a **transaction log sizing audit** and ideally validated in a staging environment replica of the WMS before any production CDC is enabled. This adds 2-4 weeks to Phase 1 prep work.

### Identified Assumption Biases
The primary proposal exhibits mild **optimism bias** in three areas:
1. Assuming the WMS schema will be interpretable without significant reverse-engineering effort.
2. Assuming WiFi/network coverage is uniform across the facility.
3. Assuming reflash stations can be automated (no validation of this).

---

## Data Insights

*(Based on Sofia Reyes's quantitative analysis; specific figures are industry-benchmark estimates pending actual Dell operational data)*

### Estimated Transaction Volume

| Scenario | Daily Transactions | Peak TPS (Shift Start) | Notes |
|:---|---:|---:|:---|
| Conservative (current scale) | ~50,000 | ~25 TPS | 50 concurrent workers, normal ops |
| Target (optimized throughput) | ~150,000 | ~75 TPS | Including all device events |
| Peak (Black Friday equivalent) | ~300,000 | ~150 TPS | All zones active, expedited orders |

**Implication:** SQL Server on modern hardware handles 10,000+ TPS for simple inserts. The 150 TPS peak is **well within SQL Server's envelope** — *if* the CQRS separation is in place. Without separation, concurrent analytical reads during peak writes can reduce effective write throughput by 60-80% under latch contention.

### Latency Budgets

| Operation | Target | Notes |
|:---|:---|:---|
| Scan → Ledger Write Confirmation | < 500ms | Includes network round-trip; must feel instantaneous |
| Wave Engine Analysis | < 5 minutes | Acceptable for batch planning; real-time not required |
| CDC Lag (WMS → WMTS) | < 30 seconds | Acceptable for shadow phase; Phase 2 may need tighter SLA |
| Dashboard Refresh | < 60 seconds | PowerBI/reporting read side |

### Storage Sizing

| Component | Estimate | Growth |
|:---|:---|:---|
| Transaction Ledger (1 year) | ~20-50 GB | Linear with transaction volume |
| Serial Number Index | ~5-10 GB | Depends on tracked unit count |
| CDC Raw Log Storage | ~100 GB/year | Depends on WMS transaction rate |
| Total (3-year projection) | ~500 GB | Well within SQL Server Hyperscale or on-prem SAN |

**Takeaway:** Storage is not a constraint. This is a throughput and contention problem, not a volume problem.

### Technology ROI Signal
- **Phase 1 (Shadow Ledger):** Minimal ROI visibility but enables all subsequent phases. Primary value is risk reduction — catching WMS data anomalies before they manifest as operational problems.
- **Phase 2 (Active Pilot on Reflash Zone):** Measurable reduction in reflash cycle time if station automation is achieved. Estimated 15-30% throughput improvement in the zone based on comparable depot studies.
- **Phase 3 (Full Control + Wave Optimization):** Primary ROI driver. Reduced mis-picks, reduced inventory cycle count frequency, reduced emergency re-orders from phantom stock deficits.

---

## Confidence Levels

| Conclusion | Confidence | Rationale |
|:---|:---:|:---|
| Ledger/transaction model is the correct foundational architecture | **High** | Validated by D365, SAP EWM; logical correctness; all three specialists agree |
| In-transit state is a mandatory schema addition | **High** | Logical deduction from the status lifecycle; Webb independently identifies the gap; no counterargument found |
| Wave invalidation requires task-locking for `assigned`/`in_transit` | **High** | Industry precedent (D365 hard allocation); race condition is deterministic |
| CDC is preferred WMS observability strategy | **High** | Industry standard; multiple independent endorsements; risks are known and mitigable |
| CQRS separation is required at target scale | **High** | Transaction volume math confirms; latch contention under mixed workload is well-documented SQL Server behavior |
| Transaction UUIDs must be embedded in scan instructions | **High** | Logical necessity for concurrent-move disambiguation; no credible alternative |
| Offline-first mobile design is required | **High** | Physical reality of warehouse RF dead zones; D365 design precedent |
| WorkOrder entity required for reflash/SKU change | **High** | Logical necessity; no other model closes the ledger without permanent drift |
| Zone Coordinator needs distributed design | **Moderate** | The SPOF concern is valid; specific mitigation design not yet specified |
| Phase duration estimates (3-month phases) | **Moderate** | Highly dependent on WMS schema legibility, which is unknown |
| Reflash station automation is achievable | **Low** | No information on station capabilities; this assumption drives significant Phase 2 design decisions |
| WMS write-back API exists | **Low** | Explicitly an open question; if absent, Phase 2 integration strategy requires complete redesign |
| Actual peak TPS figures | **Low** | Based on industry estimates, not measured Dell operational data |

---

## Recommendations

### Decisions That Can Be Made Now (High-Confidence Basis)

1. **Adopt the Ledger Model with the Revised Status Lifecycle.** Commit to the append-only transaction table design with the **six-state lifecycle** (`planned → assigned → in_transit → fulfilled | cancelled | invalidated`) before any schema work begins. This is non-negotiable and any deviation is a regression to a simpler but incorrect model.

2. **Implement CQRS from Day 1.** The `MovementTransactions` write table and the analytical read projection must be separate from the moment the first line of schema code is written. Retrofitting this after Phase 1 is significantly more disruptive than doing it upfront.

3. **Mandate Transaction UUIDs in All Device Interactions.** All scanner task flows, pick list printouts, and putaway instructions must encode and return the Transaction UUID. This rule should be enforced at the API contract level — any device event without a Transaction UUID should be rejected or quarantined for manual review.

4. **Prohibit Wave Invalidation of In-Progress Transactions.** Implement the two-pass wave conflict resolution algorithm as a hard architectural constraint. Add this to the Wave Manager's API contract as an assertion, not just a guideline.

5. **Use CDC for WMS Observability; Never Direct Operational DB Queries.** This policy decision should be made and communicated to the DBA/operations team immediately, as enabling CDC requires their cooperation and advance planning.

6. **Model the WorkOrder Entity for All Dell-Specific Transformation Operations.** Reflash, repair, and RMA triage all require the WorkOrder wrapper. This is not a Phase 3 concern — it is required before Phase 1 can correctly reconcile with WMS data that includes these operations.

---

### Areas Requiring Additional Research Before Decisions

7. **WMS Write-Back API Discovery (Blocks Phase 2 Design).**
   Conduct a deep-dive session with whoever built or maintains the legacy WMS to answer: *Does it expose any API surface (REST, SOAP, stored procedure) for receiving inventory updates, or is direct table access the only path?* If direct table access is the only path, a **strict façade layer with a full rollback strategy** must be designed before Phase 2 begins. If no API exists, seriously evaluate whether Phase 2 should be limited to writing only to WMTS (treating WMS as eventually consistent) rather than writing back.

8. **WMS Schema Reverse-Engineering Sprint (Blocks Phase 1 CDC Design).**
   Before enabling CDC, the team needs a 2-4 week schema analysis sprint to map WMS table names and columns to semantic meaning. Without this, CDC streams raw table events that are uninterpretable. This sprint should produce a `WMS Schema Rosetta Stone` document that maps table/column → domain concept.

9. **Reflash Station Capability Assessment (Blocks Phase 2 Automation Design).**
   Interview the repair operations team to determine whether reflash stations can send HTTP or MQTT events autonomously, or whether they require a human operator to manually log pass/fail. If manual, the Phase 2 scanner workflow is the only integration path. If automated, the station becomes a first-class device emitting `DeviceEvent` records and unlocks significant throughput gains.

10. **Device Hardware Audit (Blocks Mobile App Technology Selection).**
    Identify the specific handheld devices deployed (Zebra, Honeywell, iOS, Android). This determines whether the mobile app is built as **.NET MAUI** (native device APIs for hardware scanners), **Blazor Hybrid**, or a **Progressive Web App**. Starting MAUI development before this is answered risks a full rewrite.

---

### Specific Follow-Up Questions That Would Most Improve Confidence

| Question | Who to Ask | Confidence Gain |
|:---|:---|:---:|
| Does the WMS expose an API for write-back? | WMS owners/maintainers | Unlocks Phase 2 planning |
| What is the actual daily transaction count in the WMS today? | DBA / Operations | Validates all volume estimates |
| Can CDC be enabled on the WMS DB without operations team veto? | IT/DBA | Unlocks Phase 1 observability strategy |
| What are the physical zone boundaries and do "in-transit" zones exist (e.g., forklifts, conveyor)? | Warehouse floor ops | Refines zonal decomposition design |
| What is the firmware versioning strategy — does reflash change the SKU string or a dimension/attribute? | Dell integration team | Determines WorkOrder schema specifics |

---

### Risks of Acting on Low-Confidence Conclusions

- **Do not size infrastructure based on current volume estimates.** Build with horizontal scaling capability (Azure SQL Hyperscale elastic pool, or SQL Server with AlwaysOn for on-prem) so that when real throughput numbers are known, scaling is a configuration change, not an architectural change.

- **Do not design Phase 2 as if the WMS has a write-back API.** Treat it as unknown. Phase 2 must have two codepaths ready: one assuming API access, one assuming WMTS is the authoritative system and WMS reconciles on a delay.

- **Do not commit to 3-month phase timelines in any contract or stakeholder promise.** The WMS schema reverse-engineering timeline is the critical path wildcard. A cryptic schema with embedded stored procedure logic could double or triple Phase 1 duration.

---

## Architecture Decision Log: Non-Negotiables

The following decisions are established at **High Confidence** and should be treated as locked:

| # | Decision | Rationale |
|:--|:---|:---|
| ADR-001 | Append-only transaction ledger with six-state lifecycle | Correctness invariant; industry validated |
| ADR-002 | Transaction UUIDs embedded in all scan instructions | Only viable disambiguation strategy |
| ADR-003 | `assigned`/`in_transit` transactions are immune to wave invalidation | Race condition prevention; physical reality requirement |
| ADR-004 | CQRS: write and read paths are separate from initial schema design | Scale requirement at target TPS |
| ADR-005 | CDC (not polling) for WMS observability | Operational safety; accuracy requirement |
| ADR-006 | WorkOrder entity wraps all SKU-transforming operations | Ledger correctness for Dell workflows |
| ADR-007 | Offline-first mobile architecture; SignalR for UX only, never for consistency | Physical warehouse environment requirement |
| ADR-008 | SQL Server Ledger Tables on `MovementTransactions` | Tamper-evident audit trail; Microsoft stack native |
| ADR-009 | No direct reads or writes to WMS operational database from WMTS | Operational safety; WMS is not owned by this team |

---

*Research confidence is highest on architectural patterns and design correctness. It is lowest on Dell-specific operational parameters (actual volumes, device types, WMS API surface) which require direct discovery. Phase 1 should be treated as a discovery phase as much as a build phase — the Shadow Ledger is also a reverse-engineering exercise.*