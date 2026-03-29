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

---

## Plan Review

### Critical Issues

**1. Spike questions already answered — plan architecture is wrong.**
`create_session()` accepts both `mcp_servers: dict[str, MCPServerConfig]` and `skill_directories: list[str]` as per-session parameters (client.py:1073, 1077). `SubprocessConfig` has no MCP config field — it's process-level connection config only. The framing of "Does SubprocessConfig accept additional_mcp_config?" and "does MCP require one client per template?" is based on a false premise. Both are already first-class per-session SDK params.

**2. `agent.py::create_session` is missing from the plan — this is where the work happens.**
The orchestrator's `_spawn()` calls `agent.create_session(self.client)` (agent.py:76). That method calls `client.create_session()` with a hardcoded set of kwargs — no `mcp_servers`, no `skill_directories`. Phase 1 and 2 require modifying `SwarmAgent.create_session()` to accept and pass these params. The plan says to modify `orchestrator.py` and `template_loader.py` but never mentions `agent.py`.

**3. Leader and synthesis sessions also call `_create_session_with_tools()` without MCP/skills.**
`orchestrator.py::_plan()` and `_synthesize()` both call `_create_session_with_tools()`. The plan only discusses workers. If leader/synthesis agents also need template MCP tools, those callsites are unaddressed. `_create_session_with_tools` has a fixed signature — adding `mcp_servers` and `skill_directories` means changing the helper or bypassing it.

**4. `MCPLocalServerConfig` requires a `tools` field — plan's YAML schema omits it.**
SDK's `MCPLocalServerConfig` includes a `tools: list[str]` field (tools to expose; `[]` means none, `"*"` means all). The plan's `mcp-servers.yaml` example doesn't include this. Without it, the MCP server may register but expose no tools, silently failing.

**5. Zip-deployed templates will fail `format_goal()` at runtime.**
`rest.py::start_swarm` calls `format_goal(request.template, request.goal)` which reads from hardcoded `TemplateSpec` objects in `templates.py`, not from `_template.yaml`'s `goal_template` field. A zip-deployed template key won't be in that dict — `format_goal()` will raise `KeyError`. Phase 3 doesn't address this.

**6. Zip extraction is a zipslip vector.**
Phase 3 needs explicit defense against archive entries with `../` paths. Python's `zipfile` does not sanitize entry names. The plan notes "validate structure" but doesn't specify path sanitization before extraction.

### Assumptions to Verify

**1. No AGENTS.md copying needed — `skill_directories` is already a per-session param.**
`create_session()` accepts `skill_directories: list[str]` directly. The entire discussion of deploying to `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`, flattening to AGENTS.md, and target CLI adapters is unnecessary. Pass `str(template_dir / "skills")` at session creation. Phase 2 is much simpler than described.

**2. `skill_directories` is per-session, not process-level.**
Template skills are isolated to swarms using that template. No cross-contamination between concurrent swarms using different templates. The spike question is already answered.

**3. One `CopilotClient` is sufficient for all templates.**
`mcp_servers` is per-session. No need for one client per template.

### Missing Pieces

**1. Hot reload is partially broken.**
`_template_loader` is instantiated once in `lifespan()`. `list_available()` and `load()` re-read from disk, so newly deployed templates are accessible. However, server-level concerns (e.g., a `system-prompt.md` at templates root) won't be picked up without restart. Phase 3 should document this limitation.

**2. `get_template_details` (rest.py:299) uses `iterdir()` — won't recurse into `skills/`.**
After Phase 2 adds a `skills/` subdirectory, the template detail endpoint silently omits skill files.

**3. No zip size/count limits.**
No mention of maximum zip size, maximum extracted size, or file count. An adversarial upload could exhaust disk.

**4. Directory name must match `_template.yaml` key.**
`load()` uses `meta["key"]` from inside YAML; routing uses `subdir.name`. A zip with a mismatched inner key will produce an unreachable or colliding template. Phase 3 validation must enforce that the zip's directory name matches the `key` field.

**5. Concurrent swarm MCP subprocess exhaustion.**
Each swarm using a stdio MCP server spawns a fresh subprocess per `create_session()` call. 10 concurrent swarms each spawning playwright subprocesses is a real resource exhaustion risk. No mention of pooling or limits.

**6. `_create_session_with_tools()` mock fallback silently drops MCP/skill config.**
The `except TypeError` fallback (orchestrator.py:53-55) calls `create_session(tools=tools)` with no MCP/skill params. Tests will pass while production behavior diverges.

### Minor Notes

- Plan's YAML uses `type: stdio`; confirm the SDK's `MCPLocalServerConfig` accepts this spelling vs `"local"`.
- Phase 1 and 2 are both just additional `create_session` kwargs — artificial split adds coordination cost. Consider implementing together.
- Explicit decision needed: should leader and synthesis sessions also receive template MCP servers? The plan is silent on this.

---

## Addendum: Zip Import Validation Gaps

A `template_validator.py` already exists with solid per-file frontmatter validation (required fields, tool whitelist, `{user_input}` placeholder, non-empty body). It is called on file edits via the API but **not during template load**, meaning zip-imported templates could bypass it entirely. Phase 3 must explicitly call `validate_template_file()` on each extracted file before committing to disk.

### What can be reused from the existing validator

- Required field checks: `key`, `name`, `description`, `goal_template` (`_template.yaml`); `name`, `displayName`, `description` (worker files)
- Tool whitelist: `task_update`, `inbox_send`, `inbox_receive`, `task_list`
- `{user_input}` placeholder in `goal_template`
- Non-empty body check for `leader.md` and `synthesis.md`

### Gaps that need to be added for zip import

| Risk | Current state | Required |
|---|---|---|
| **Zipslip** | No upload endpoint exists yet; no member path sanitization | Sanitize all archive member paths before extraction — strip or reject any entry containing `../` or absolute paths |
| **YAML bombs** | `yaml.safe_load()` used everywhere — safe from code execution, not from deeply nested anchor DoS (`&x [*x, *x]`) | Spike: cap file size pre-parse, or evaluate `ruamel.yaml` with depth limits |
| **Size/count limits** | No limits anywhere in current codebase | Enforce max zip size, max extracted size, max file count |
| **Key/directory mismatch** | Not checked | Zip root directory name must match `_template.yaml` `key` field — validate before extraction completes |
| **Frontmatter on import** | Validator not called during load | Call `validate_template_file()` on each extracted file; fail the entire import (and clean up) if any file is invalid |

### Spike required: YAML bomb protection

`yaml.safe_load()` does not protect against anchor expansion attacks. This needs a dedicated spike before Phase 3 implementation. Options:
- Pre-parse file size cap (simplest — reject any single YAML file over e.g. 64KB before parsing)
- `ruamel.yaml` with explicit depth/alias limits
- Custom YAML loader that caps alias count

Recommended: size cap is the simplest and has no new dependencies. Determine a reasonable limit (suggested: 64KB per file, 1MB total extracted YAML) and document it.
