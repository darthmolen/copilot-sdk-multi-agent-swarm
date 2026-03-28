# Plan: Template Packs — MCP Servers, Skills, and Zip Deploy

## Context

Templates currently define agents and prompts but can't bundle MCP servers or skills. At enterprise scale, teams need portable "template packs" — a template + its MCP server configs + its skills — deployable as a single zip. Skills follow the agentskills.io / AGENTS.md standard and land in the copilot CLI's discovery path so agents pick them up naturally.

## Architecture

### Three layers of a Template Pack

```
my-template-pack.zip
├── _template.yaml          # Existing: metadata, goal_template
├── leader.md               # Existing: leader prompt
├── worker-*.md             # Existing: worker definitions
├── synthesis.md            # Existing: synthesis prompt
├── mcp-servers.yaml        # NEW: MCP server definitions for this template
└── skills/                 # NEW: portable agentskills.io convention
    ├── domain-expertise/
    │   └── skill.md
    └── tool-usage-guide/
        └── skill.md
```

**Pack format is portable** (agentskills.io `skills/{name}/skill.md` convention). The deploy step transforms to match the target CLI:
- Copilot CLI: flatten to AGENTS.md or custom instructions dir
- Claude Code: copy to `skills/{name}/skill.md` as-is
- Other CLIs: adapter per target

### How each layer works

**MCP Servers** — Declared in `mcp-servers.yaml` per template. At swarm startup, the orchestrator passes these to the copilot CLI via `--additional-mcp-config` (SubprocessConfig flag). Agents in that swarm get the MCP tools alongside the built-in swarm tools.

```yaml
# mcp-servers.yaml
servers:
  playwright:
    type: stdio
    command: npx
    args: ["-y", "@playwright/mcp@latest"]
  custom-db:
    type: stdio
    command: python
    args: ["-m", "my_mcp_server"]
```

**Skills** — `.md` files with YAML frontmatter in the template's `skills/` directory. At deploy time, copied to the copilot CLI's custom instructions path (`COPILOT_CUSTOM_INSTRUCTIONS_DIRS` or `.github/AGENTS.md` equivalent). The LLM discovers them naturally — no custom conditional logic needed.

```markdown
---
name: warehouse-domain
description: Domain expertise for warehouse optimization
---

# Warehouse Domain Knowledge

When analyzing warehouse layouts, always consider...
```

**Zip Deploy** — Upload a `.zip` via API endpoint. Backend validates structure, extracts to `src/templates/{key}/`, copies skills to copilot instructions path. Server-level MCP configs merge with template-level at runtime.

### Server-level vs Template-level

| Config | Server-level | Template-level |
| ------ | ------------ | -------------- |
| MCP servers | `~/.copilot/mcp-config.json` | `src/templates/{key}/mcp-servers.yaml` |
| Skills | `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` | `src/templates/{key}/skills/*.md` |

Server-level = always available to all swarms. Template-level = only active when that template is used.

## Implementation Phases

This is too large for one PR. Three phases:

### Phase 1: MCP Server Config per Template

**Files to modify:**

- `src/backend/swarm/template_loader.py` — Parse `mcp-servers.yaml` from template dirs. Add `mcp_servers: dict` to `LoadedTemplate`.
- `src/backend/swarm/orchestrator.py` — Pass MCP config when creating agent sessions. The copilot SDK's `SubprocessConfig` or `create_session` may accept MCP config.
- `src/backend/main.py` — Check if `SubprocessConfig` accepts `additional_mcp_config` or if we need to pass it per-session.

**Key question to spike:** Does `create_session()` accept MCP config, or is MCP configured at the client level (SubprocessConfig)? If client-level only, we may need one CopilotClient per template — or pass `--additional-mcp-config` at client start.

### Phase 2: Skills per Template

**Files to modify:**

- `src/backend/swarm/template_loader.py` — Discover `skills/*.md` files in template dirs. Add `skills: list[SkillDefinition]` to `LoadedTemplate`.
- `src/backend/swarm/prompts.py` — Inject skill content into agent prompts (append to system preamble or worker prompt). OR: copy skills to `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` so the CLI discovers them natively.
- Deploy path: determine where the copilot CLI looks for custom instructions and write skills there.

**Decision point:** Inject skills into prompts ourselves (full control, works with any LLM backend) vs. deploy to copilot CLI path (leverages native discovery, but coupled to copilot CLI).

### Phase 3: Zip Deploy

**Files to modify:**

- `src/backend/api/rest.py` — New `POST /api/templates/deploy` endpoint accepting a zip file.
- `src/backend/api/schemas.py` — Request schema for deploy.
- Validation: check zip structure (must have `_template.yaml`, validate all files).
- Extraction: unzip to `src/templates/{key}/`, copy skills to instructions path.
- Hot reload: `TemplateLoader` re-discovers templates after deploy.

## What Needs Spiking First

Before writing the full implementation plan, we need answers to:

1. **Does `SubprocessConfig` or `create_session` accept MCP config?** — Check the copilot SDK source. If MCP is client-level only, architecture changes.
2. **Does `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` work per-session?** — Or is it process-level? If process-level, template skills would be visible to ALL swarms, not just the one using that template.
3. **Can the copilot CLI's `--additional-mcp-config` be passed per-session?** — Or only at process start?

## Next Steps

1. Spike the copilot SDK to answer the three questions above
2. Based on answers, finalize Phase 1 implementation plan
3. TDD implementation of Phase 1
4. Phase 2 and 3 follow

## Verification

- Phase 1: Create a template with `mcp-servers.yaml` referencing playwright. Run a swarm. Agent should have playwright tools available.
- Phase 2: Create a template with `skills/domain.md`. Run a swarm. Agent prompt should include the skill content.
- Phase 3: Upload a zip via API. Verify template appears in list and is usable.
