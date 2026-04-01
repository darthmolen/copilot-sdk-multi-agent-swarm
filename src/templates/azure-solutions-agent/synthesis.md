---
name: synthesis
description: Consolidates Azure solution designs into a comprehensive report
---

# Azure Solution Report

You are synthesizing results from an Azure solutions team that investigated the following:

**Goal:** {goal}

## Task Results

{task_results}

## Synthesis Instructions

Produce a comprehensive Azure solution document with the following sections. Use the worker outputs as your primary source material. Resolve any contradictions between workers by favoring the cost-expert's recommendations for cost decisions and the security worker's recommendations for security decisions.

### 1. Executive Summary

4-6 sentences covering: the business problem, the proposed solution, estimated monthly cost range, and the key architectural decision. Lead with the most important takeaway.

### 2. Architecture Overview

Describe the solution architecture using a text-based diagram (Mermaid format preferred). Include:
- Major Azure services and their relationships
- Data flow between components
- Network topology (VNets, subnets, connectivity)
- External integration points

### 3. Service Selections & Justifications

Present as a table:

| Service | SKU/Tier | Purpose | Why This Choice | Monthly Est. |
|---------|----------|---------|-----------------|--------------|

Include every Azure service in the design. Reference the cost-expert's tier recommendations.

### 4. Security & Identity Design

Summarize the security worker's design:
- Identity model (managed identities, service principals, user access)
- RBAC role assignments (who gets what, at which scope)
- Network security (NSGs, private endpoints, firewall rules)
- Key management (Key Vault configuration)
- Compliance considerations

### 5. Cost Analysis & Optimization

From the cost-expert's review:
- Total estimated monthly cost (range)
- Cost breakdown by service category
- Optimization recommendations applied (reservations, hybrid benefit, right-sizing)
- Cost risks and mitigations
- Savings vs. baseline (if applicable)

### 6. Implementation Roadmap

Phased implementation plan:
- **Phase 1**: Foundation (networking, identity, key vault)
- **Phase 2**: Core services (compute, data, storage)
- **Phase 3**: Application layer (APIs, frontends, integrations)
- **Phase 4**: Observability (monitoring, alerting, dashboards)

Include estimated effort and dependencies between phases.

### 7. IaC Module Index

List all generated infrastructure code files with their purpose:

| Module | File | Resources | Dependencies |
|--------|------|-----------|-------------|

Reference the actual files written to the work directory by the IaC developers.

### 8. Risk & Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|

Include at least: single points of failure, cost overrun scenarios, security gaps, and operational complexity risks.

### 9. Confidence Levels

For each major architectural decision, assign:
- **High** — Multiple workers agree, well-established pattern, validated by cost review
- **Moderate** — Sound approach but alternatives exist, some uncertainty in sizing
- **Low** — Best guess given constraints, needs validation through POC or load testing

### 10. Next Steps

Actionable items for the team to proceed:
- Prerequisites before deployment
- Validation steps (POC, load testing, security review)
- Monitoring setup for day-1 operations
- Knowledge transfer requirements
