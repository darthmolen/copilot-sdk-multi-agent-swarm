---
name: azure-cost-optimization
displayName: Azure Cost Optimization
description: Cost analysis frameworks — reservation strategies, right-sizing, Hybrid Benefit, budget management, TCO analysis, and cost allocation patterns
---

# Azure Cost Optimization

You reduce Azure spend without reducing capability. Cost optimization is not about being cheap — it is about eliminating waste and matching spend to value. When a question involves specific pricing, SKU costs, reservation discounts, or Azure Advisor recommendations, use the `microsoft_docs_search` and `microsoft_docs_fetch` MCP tools to retrieve current numbers rather than quoting from memory.

## Cost Optimization Priority Framework

Attack costs in this order. The first items save the most with the least effort.

### Priority 1: Eliminate Waste (Immediate, zero risk)

**Actions:**
- Delete orphaned disks, public IPs, and NICs not attached to any resource
- Shut down or delete non-production VMs running 24/7 (auto-shutdown schedules)
- Remove empty App Service Plans (they still cost money)
- Delete unused Application Gateways, VPN Gateways, and Azure Firewalls (these bill hourly even idle)
- Remove old snapshots and unattached managed disks
- Check for abandoned resources from failed deployments

**Detection method:** Azure Advisor cost recommendations + Azure Resource Graph queries. Use `microsoft_docs_search` to find current Resource Graph query examples for orphaned resources.

### Priority 2: Right-Size (Days, low risk)

**Actions:**
- Analyze VM CPU/memory utilization over 14+ days — if average < 40%, downsize
- Review App Service Plan metrics — if CPU never exceeds 30%, drop a tier
- Check Azure SQL DTU/vCore usage — most databases are over-provisioned by 2-3x
- Review Cosmos DB RU consumption — autoscale saves money for variable workloads
- Check Redis cache hit ratio — if it is low, you may not need Redis at all

**Right-sizing rules of thumb:**
| Metric (14-day average) | Action |
|---|---|
| CPU < 5% | Candidate for deletion or serverless |
| CPU 5-20% | Downsize by 2 tiers |
| CPU 20-40% | Downsize by 1 tier |
| CPU 40-70% | Properly sized |
| CPU > 70% sustained | Consider upsizing or scaling out |
| Memory > 80% constant | Memory-optimized SKU needed |

**Common over-provisioning patterns:**
- D-series VMs when B-series (burstable) would suffice for low-utilization workloads
- Premium SSD for databases with sequential read patterns (Standard SSD is fine)
- Premium Redis when Standard tier meets throughput requirements
- S3 App Service Plan when S1 would handle the traffic

### Priority 3: Optimize Pricing Models (Weeks, medium commitment)

#### Reservations

**When to reserve:**
- Workload has been running at stable utilization for 30+ days
- You are confident it will continue for 1 or 3 years
- The resource cannot be easily replaced by a different SKU

**Reservation decision matrix:**

| Confidence Level | Recommendation |
|---|---|
| Will run for 3+ years, same SKU | 3-year reservation (up to 72% savings) |
| Will run for 1+ years, same SKU | 1-year reservation (up to 40% savings) |
| Will run but SKU may change | 1-year reservation with instance size flexibility |
| Uncertain duration | Pay-as-you-go (do not reserve) |
| Variable workload | Savings Plans (more flexible than reservations) |

**Reservation scope strategy:**
- Shared scope (across all subscriptions) — maximizes utilization across the organization
- Management group scope — balances flexibility and governance
- Single subscription — only when chargeback requires strict isolation

**Savings Plans vs Reservations:**
- Savings Plans: commit to hourly dollar amount, applies to any compute (VMs, Container Apps, Functions Premium). More flexible.
- Reservations: commit to specific SKU instance. Deeper discount but less flexible.
- Can combine both: reservation fills first, savings plan covers the rest.

Use `microsoft_docs_search` to check current reservation discount percentages for specific VM families and services.

#### Azure Hybrid Benefit

**Applies when the customer owns:**
- Windows Server licenses with Software Assurance → use on VMs, AKS, App Service
- SQL Server licenses with Software Assurance → use on Azure SQL, SQL MI, SQL on VMs
- Linux subscriptions (RHEL, SUSE) → use on VMs

**Savings magnitude:** Windows Server Hybrid Benefit saves roughly 40% on VM cost. SQL Server Hybrid Benefit can save 55%+. These are significant — always ask about existing licenses early in the conversation.

**How to verify eligibility:** Customer needs to provide their EA or license details. Use `microsoft_docs_search` for "Azure Hybrid Benefit eligibility requirements" to give them the current checklist.

### Priority 4: Architectural Optimization (Months, highest impact)

**Design-level changes that reduce cost structurally:**

- Move from VMs to PaaS (App Service, Container Apps) — eliminates OS management cost
- Move from provisioned to serverless (Functions Consumption, Cosmos DB serverless) — pay only for usage
- Implement storage lifecycle policies (Hot → Cool → Cold → Archive automatically)
- Use CDN for static content instead of serving from compute
- Consolidate databases — five underutilized Azure SQL databases may cost more than one elastic pool
- Replace always-on batch VMs with Container Apps Jobs or Azure Batch spot instances

## Dev/Test Cost Strategies

**Non-negotiable for every engagement:**
- Apply dev/test pricing on non-production subscriptions (up to 55% savings on Windows VMs)
- Auto-shutdown VMs at end of business day (schedule via Azure policy)
- Use B-series (burstable) VMs for all dev/test workloads
- Azure SQL Basic or serverless tier for dev databases
- Storage with LRS (no geo-redundancy needed for dev data)
- Delete and recreate environments with IaC instead of keeping them running

**Dev/test subscription setup:** Create a separate subscription linked to an EA Dev/Test offer or Visual Studio Enterprise subscription. This unlocks discounted pricing automatically for most services.

## Cost Allocation and Chargeback

**Tagging strategy (minimum viable):**

| Tag | Purpose | Example |
|---|---|---|
| cost-center | Financial chargeback | CC-4521 |
| environment | Dev/test vs production pricing | prod, staging, dev |
| owner | Who to contact about resources | team-platform |
| project | Group costs by initiative | project-phoenix |
| managed-by | IaC or manual | terraform, manual |

**Enforcement:**
- Use Azure Policy to require tags at resource group level (deny deployment without tags)
- Inherit tags from resource group to resources automatically via policy
- Run monthly compliance reports — untagged resources cannot be charged back

**Cost Management views:**
- Create cost views per cost-center tag for finance team
- Create cost views per environment for engineering leads
- Set up budget alerts at 50%, 75%, 90%, and 100% of monthly allocation
- Export cost data to Storage Account for custom reporting

## Budget and Alert Configuration

**Alert thresholds:**

| Threshold | Action |
|---|---|
| 50% of monthly budget | Informational email to team lead |
| 75% of monthly budget | Warning to engineering manager |
| 90% of monthly budget | Alert to finance + engineering director |
| 100% of monthly budget | Action required — review and justify or reduce |
| Anomaly detection | Immediate alert on cost spikes (Azure Cost Management anomaly alerts) |

**Anomaly detection:** Azure Cost Management has built-in anomaly detection. Enable it. A sudden 3x spike in a single day usually means a misconfigured autoscale, a runaway deployment, or a forgotten dev resource scaled to production tier.

## TCO Analysis Framework

**When comparing on-premises to Azure (or vice versa), include all costs:**

**On-premises costs people forget:**
- Power and cooling (typically 30-40% of hardware cost)
- Physical space and rack rental
- Network hardware (switches, firewalls, load balancers)
- Staff time for patching, hardware refresh, firmware updates
- Software licenses for hypervisor, backup, monitoring
- Overprovisioning buffer (typically 30-50% extra capacity for peaks)
- Disaster recovery site costs (secondary datacenter)

**Azure costs people forget:**
- Data egress charges (outbound to internet or other regions)
- Premium support contract ($1,000/month for Business, more for Enterprise)
- Third-party marketplace costs (NVAs, security tools)
- Training and certification for team
- Management and monitoring tooling
- ExpressRoute circuit monthly fees

**TCO comparison rules:**
- Compare 3-year TCO, not monthly cost
- Include labor costs for both scenarios
- Factor in the opportunity cost of staff spending time on infrastructure vs. features
- Be honest about Azure costs — hiding egress charges makes the analysis lose credibility

Use `microsoft_docs_search` for the current Azure Pricing Calculator and TCO Calculator URLs and guidance.

## Spot VMs

**When to use:**
- Batch processing that can be interrupted and restarted
- Dev/test environments where occasional eviction is acceptable
- Stateless scale-out tiers behind a load balancer (eviction loses one node, not the service)
- CI/CD build agents (rebuild on eviction)

**When NOT to use:**
- Production databases (eviction = data loss risk)
- Singleton services with no redundancy
- Workloads that cannot handle interruption within 30 seconds

**Savings:** Spot VMs are typically 60-90% cheaper than pay-as-you-go. Use `microsoft_docs_search` to check current spot pricing and eviction rates for specific VM families and regions.

**Eviction strategy:**
- Use eviction type "Deallocate" (not Delete) to preserve disks
- Set max price to -1 (pay up to pay-as-you-go, accept eviction only on capacity) for lowest eviction risk
- Implement graceful shutdown handlers in your application
- Combine spot with on-demand in a scale set (spot for baseline, on-demand for overflow)

## Azure Advisor Integration

**Review cadence:**
- Weekly: automated digest of cost recommendations to team channel
- Monthly: human review of all Advisor recommendations with action/dismiss decisions
- Quarterly: full cost optimization review with stakeholders

**High-value Advisor recommendations to prioritize:**
1. Shut down underutilized VMs (immediate savings)
2. Buy reservations for consistent usage (30-72% savings)
3. Right-size or shut down underperforming VMs
4. Use Standard SSDs where Premium is unnecessary
5. Delete unused public IP addresses ($3.65/month each adds up)

## MCP Tool Usage

- Use `microsoft_docs_search` for current pricing for specific Azure services, reservation discount percentages, Hybrid Benefit eligibility, and Spot VM pricing
- Use `microsoft_docs_fetch` for detailed Azure Cost Management setup guides, budget API documentation, and Advisor REST API reference
- Always verify pricing through MCP tools — Azure pricing changes frequently and varies by region, EA agreement, and tier
- When recommending Azure CLI commands for cost management (az consumption, az costmanagement), fetch current syntax through MCP tools
- Use `microsoft_docs_search` with "Azure Pricing Calculator" to direct customers to the current calculator for detailed estimates
