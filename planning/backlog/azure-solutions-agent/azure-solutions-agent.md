# Plan: Azure Solutions Agent Template

## Context

A comprehensive Azure solutions template pack that bundles domain-expert skills covering the full breadth of Azure architecture, engineering, and operations. Each skill is a standalone `.md` file following the agentskills.io convention (`skills/{name}/skill.md`), giving agents deep domain expertise when assigned tasks in that area.

The template uses the Microsoft Learn MCP server for real-time access to official documentation — agents can look up current Azure service details, pricing tiers, CLI commands, and best practices rather than relying on training data.

## Template Structure

```
azure-solutions-agent/
├── _template.yaml
├── leader.md                    # Azure Solutions Architect leader
├── synthesis.md                 # Consolidation prompt
├── worker-architect.md          # Cloud architecture design
├── worker-engineer.md           # Infrastructure implementation
├── worker-security.md           # Security + RBAC + compliance
├── worker-ai-ml.md              # AI/ML services specialist
├── mcp-servers.yaml             # Microsoft Learn MCP
└── skills/
    ├── azure-architect/
    │   └── skill.md
    ├── azure-engineer/
    │   └── skill.md
    ├── azure-network-engineer/
    │   └── skill.md
    ├── azure-solutions-expert/
    │   └── skill.md
    ├── azure-ai-expert/
    │   └── skill.md
    ├── azure-kubernetes-expert/
    │   └── skill.md
    ├── azure-developer/
    │   └── skill.md
    ├── azure-ml-engineer/
    │   └── skill.md
    ├── azure-security-expert/
    │   └── skill.md
    └── entra-expert/
        └── skill.md
```

## MCP Server

```yaml
servers:
  microsoft-learn:
    type: http
    url: https://learn.microsoft.com/api/mcp
    tools: ["*"]
```

All agents get `microsoft_docs_search`, `microsoft_docs_fetch`, and `microsoft_code_sample_search` for real-time documentation access.

## Skills — What Each Covers

### azure-architect
Cloud architecture patterns, Well-Architected Framework (WAF) pillars, landing zones, hub-spoke topology, multi-region design, disaster recovery patterns, CAF (Cloud Adoption Framework), architecture decision records. When to use App Service vs AKS vs Container Apps vs Functions. Tier selection guidance.

### azure-engineer
ARM/Bicep templates, Terraform for Azure, Azure CLI (`az`) commands, resource provisioning, deployment automation, Azure DevOps pipelines, GitHub Actions for Azure, infrastructure-as-code patterns, resource naming conventions, tagging strategies, cost management.

### azure-network-engineer
VNets, subnets, NSGs, ASGs, Azure Firewall, Application Gateway, Front Door, Private Endpoints, Private Link, VPN Gateway, ExpressRoute, DNS (Azure DNS + Private DNS Zones), load balancing (ALB vs Traffic Manager vs Front Door), network peering, UDR, service endpoints vs private endpoints decision matrix.

### azure-solutions-expert
End-to-end solution design, integration patterns (Logic Apps, Service Bus, Event Grid, Event Hubs), data flow architecture, hybrid connectivity, migration strategies (assess → migrate → optimize), Azure Migrate, cost optimization, SLA composition, monitoring strategy (Application Insights, Azure Monitor, Log Analytics).

### azure-ai-expert
Azure OpenAI Service (models, deployments, quotas, content filtering), Azure AI Search (formerly Cognitive Search — indexes, skillsets, semantic ranking), Azure AI Studio, Prompt Flow, Azure AI Document Intelligence, Azure Bot Service, Responsible AI practices, RAG patterns on Azure.

### azure-kubernetes-expert
AKS cluster design (node pools, availability zones, CNI vs kubenet), AKS networking (ingress controllers, service mesh), AKS security (Azure AD integration, pod identity, network policies), Helm charts, KEDA autoscaling, Container Registry (ACR), AKS monitoring (Container Insights, Prometheus), GitOps with Flux/ArgoCD on AKS.

### azure-developer
App Service (deployment slots, scaling, custom domains, SSL), Azure Functions (triggers, bindings, durable functions, consumption vs premium), Container Apps (Dapr, KEDA, revision management), Static Web Apps, API Management (APIM — policies, versioning, developer portal), Azure SignalR, Azure Cache for Redis, Azure Storage (blobs, queues, tables, files), Cosmos DB (partitioning, consistency models, SDKs).

### azure-ml-engineer
Azure Machine Learning workspace, compute instances/clusters, ML pipelines, MLflow integration, model registry, managed endpoints (online + batch), AutoML, responsible AI dashboard, Azure Databricks integration, feature store, data labeling, model monitoring, AzureML SDK v2.

### azure-security-expert
RBAC (built-in roles, custom roles, role assignments, scope hierarchy), Microsoft Defender for Cloud, Azure Key Vault (secrets, keys, certificates, access policies vs RBAC), Azure Policy (built-in policies, initiatives, remediation), network security (NSG flow logs, DDoS protection), identity security (Conditional Access from Entra side), data encryption (at rest, in transit, customer-managed keys), compliance (Azure Blueprints, regulatory compliance dashboard).

### entra-expert
Microsoft Entra ID (formerly Azure AD) — app registrations, enterprise applications, service principals, managed identities (system-assigned vs user-assigned), OAuth 2.0 flows (auth code, client credentials, on-behalf-of, device code), Microsoft Graph API (permissions, scopes, delegated vs application), Conditional Access policies, B2C/B2B, single sign-on (SSO), token configuration, API permissions and consent framework.

## Worker Design

Four workers to keep the swarm manageable while covering the breadth:

| Worker | Role | Skills Applied |
| ------ | ---- | -------------- |
| **Architect** | Cloud architecture + solution design | azure-architect, azure-solutions-expert, azure-network-engineer |
| **Engineer** | Infrastructure + DevOps | azure-engineer, azure-developer, azure-kubernetes-expert |
| **Security** | Security + identity + compliance | azure-security-expert, entra-expert |
| **AI/ML** | AI services + ML platform | azure-ai-expert, azure-ml-engineer |

Each worker gets ALL skills via `skill_directories`, but their prompt emphasizes their specialization. The leader assigns tasks based on domain match.

## Implementation Steps

1. **Write skill files** — Each `skill.md` needs YAML frontmatter (name, description) and a comprehensive domain knowledge body. Use Microsoft Learn MCP to research current service details, CLI commands, and best practices for each domain.

2. **Write worker prompts** — `worker-architect.md`, `worker-engineer.md`, `worker-security.md`, `worker-ai-ml.md`. Each emphasizes their domain but instructs them to use `microsoft_docs_search` and `microsoft_docs_fetch` for current information.

3. **Write leader.md** — Azure Solutions Architect leader that decomposes goals into architecture, engineering, security, and AI/ML tasks with appropriate dependencies.

4. **Write synthesis.md** — Consolidation prompt that produces a structured Azure solution document with architecture diagram descriptions, resource list, cost estimates, and implementation roadmap.

5. **Assemble and test** — Zip the template, deploy via the new deploy endpoint, run a test swarm with a prompt like "Design an Azure architecture for a multi-tenant SaaS application with AI-powered document processing."

## Skill Writing Guidelines

Each skill should:
- Start with a clear scope statement ("You are an expert in...")
- List the key Azure services in this domain with brief descriptions
- Include decision matrices (when to use X vs Y)
- Reference Azure CLI commands where relevant (`az ...`)
- Note current naming/branding (e.g., "Azure AI Search, formerly Cognitive Search")
- Include common pitfalls and best practices
- Be 200-500 lines — comprehensive but not encyclopedic (agents can fetch docs via MCP for details)

## Open Questions

1. **Skill granularity** — 10 skills is a lot of prompt content. Should all skills be injected for every worker, or should we map specific skills to specific workers? The `skill_directories` param sends everything — we'd need per-worker skill dirs for selective injection.

2. **Skill freshness** — Azure services change fast. Should skills include version dates and instruct agents to verify via MCP? Or keep skills as conceptual frameworks and rely on MCP for specifics?

3. **Template size** — 10 detailed skills + 4 workers + leader + synthesis could be a large zip. Stay within the 3MB limit? Probably fine since it's all text.
