"""Template loader for YAML+Markdown agent template definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentDefinition:
    name: str
    display_name: str
    description: str
    tools: list[str] | None = None  # None = all tools
    infer: bool = False
    prompt_template: str = ""  # markdown body
    max_instances: int = 1  # max concurrent tasks per round
    max_retries: int | None = None  # None = use template default
    skills: list[str] | None = None  # per-worker skill directory names


@dataclass
class LoadedTemplate:
    key: str
    name: str
    description: str
    goal_template: str
    leader_prompt: str
    agents: list[AgentDefinition] = field(default_factory=list)
    synthesis_prompt: str = ""
    mcp_servers: dict | None = None
    skills_dir: Path | None = None
    all_skill_names: set[str] = field(default_factory=set)
    skill_name_map: dict[str, str] = field(default_factory=dict)  # dir_name -> skill_name
    qa_enabled: bool = False
    max_retries: int = 2  # swarm-wide default, overridable in _template.yaml


class TemplateLoader:
    """Load multi-agent swarm templates from a directory of YAML+Markdown files."""

    def __init__(self, templates_dir: str | Path) -> None:
        self.templates_dir = Path(templates_dir)

        # Load system preamble (shared across all templates)
        # Uses same frontmatter pattern as agent files — body is the prompt
        system_prompt_path = self.templates_dir / "system-prompt.md"
        if system_prompt_path.exists():
            meta, body = self.parse_frontmatter(system_prompt_path.read_text())
            self.system_preamble: str = body
            self.system_tools: list[str] = meta.get("tools", []) or []
        else:
            self.system_preamble = ""
            self.system_tools = []

    def load(self, template_key: str) -> LoadedTemplate:
        """Load a template by key from its directory."""
        template_dir = self.templates_dir / template_key
        if not template_dir.is_dir():
            raise FileNotFoundError(f"Template directory not found: {template_dir}")

        # Read _template.yaml
        meta_path = template_dir / "_template.yaml"
        if not meta_path.exists():
            raise FileNotFoundError(f"Missing _template.yaml in {template_dir}")
        meta = yaml.safe_load(meta_path.read_text())

        # Read leader.md
        leader_path = template_dir / "leader.md"
        leader_prompt = ""
        leader_meta: dict = {}
        if leader_path.exists():
            leader_meta, leader_prompt = self.parse_frontmatter(leader_path.read_text())

        # Read worker-*.md files
        agents: list[AgentDefinition] = []
        for agent_file in sorted(template_dir.glob("worker-*.md")):
            agents.append(self.parse_agent_file(agent_file))

        if not agents:
            raise ValueError(f"Template '{template_key}' has no worker agent files (worker-*.md)")

        # Read synthesis.md
        synthesis_path = template_dir / "synthesis.md"
        synthesis_prompt = synthesis_path.read_text() if synthesis_path.exists() else ""

        # Read mcp-servers.yaml (optional)
        mcp_path = template_dir / "mcp-servers.yaml"
        mcp_servers = None
        if mcp_path.exists():
            mcp_data = yaml.safe_load(mcp_path.read_text()) or {}
            mcp_servers = mcp_data.get("servers")

        # Detect skills/ directory and enumerate skill names (optional)
        skills_dir = template_dir / "skills"
        skills_dir_resolved = skills_dir if skills_dir.is_dir() else None

        skill_name_map: dict[str, str] = {}
        if skills_dir_resolved:
            for subdir in sorted(skills_dir_resolved.iterdir()):
                if not subdir.is_dir():
                    continue
                skill_file = subdir / "skill.md"
                if not skill_file.exists():
                    skill_file = subdir / "SKILL.md"
                if skill_file.exists():
                    skill_meta, _ = self.parse_frontmatter(skill_file.read_text())
                    skill_name_map[subdir.name] = skill_meta.get("name", subdir.name)

        all_skill_names = set(skill_name_map.values())

        # Validate per-worker skill references
        for agent in agents:
            if agent.skills is not None and agent.skills != ["*"]:
                unknown = set(agent.skills) - set(skill_name_map.keys())
                if unknown:
                    raise ValueError(
                        f"Worker '{agent.name}' references unknown skill directories: "
                        f"{unknown}. Available: {set(skill_name_map.keys())}"
                    )

        return LoadedTemplate(
            key=meta["key"],
            name=meta["name"],
            description=meta.get("description", ""),
            goal_template=meta.get("goal_template", ""),
            leader_prompt=leader_prompt,
            agents=agents,
            synthesis_prompt=synthesis_prompt,
            mcp_servers=mcp_servers,
            skills_dir=skills_dir_resolved,
            all_skill_names=all_skill_names,
            skill_name_map=skill_name_map,
            qa_enabled=bool(leader_meta.get("qa", False)),
            max_retries=meta.get("maxRetries", 2),
        )

    def load_all(self) -> dict[str, LoadedTemplate]:
        """Load all templates from subdirectories."""
        templates: dict[str, LoadedTemplate] = {}
        for subdir in sorted(self.templates_dir.iterdir()):
            if subdir.is_dir() and (subdir / "_template.yaml").exists():
                t = self.load(subdir.name)
                templates[t.key] = t
        return templates

    def list_available(self) -> list[dict[str, str]]:
        """Return summary dicts for API."""
        result: list[dict[str, str]] = []
        for subdir in sorted(self.templates_dir.iterdir()):
            meta_path = subdir / "_template.yaml"
            if subdir.is_dir() and meta_path.exists():
                meta = yaml.safe_load(meta_path.read_text())
                result.append(
                    {
                        "key": meta["key"],
                        "name": meta["name"],
                        "description": meta.get("description", ""),
                    }
                )
        return result

    @staticmethod
    def parse_frontmatter(content: str) -> tuple[dict, str]:
        """Split YAML frontmatter from markdown body."""
        if not content.startswith("---"):
            return {}, content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content
        metadata = yaml.safe_load(parts[1]) or {}
        body = parts[2].strip()
        return metadata, body

    @staticmethod
    def parse_agent_file(path: Path) -> AgentDefinition:
        """Parse YAML frontmatter + markdown body from an agent .md file."""
        content = path.read_text()
        metadata, body = TemplateLoader.parse_frontmatter(content)
        return AgentDefinition(
            name=metadata.get("name", path.stem),
            display_name=metadata.get("displayName", metadata.get("name", path.stem)),
            description=metadata.get("description", ""),
            tools=metadata.get("tools"),
            infer=metadata.get("infer", False),
            prompt_template=body,
            max_instances=metadata.get("maxInstances", 1),
            max_retries=metadata.get("maxRetries"),
            skills=metadata.get("skills"),
        )
