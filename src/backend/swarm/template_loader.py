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


@dataclass
class LoadedTemplate:
    key: str
    name: str
    description: str
    goal_template: str
    leader_prompt: str
    agents: list[AgentDefinition] = field(default_factory=list)
    synthesis_prompt: str = ""


class TemplateLoader:
    """Load multi-agent swarm templates from a directory of YAML+Markdown files."""

    def __init__(self, templates_dir: str | Path) -> None:
        self.templates_dir = Path(templates_dir)

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
        if leader_path.exists():
            _, leader_prompt = self.parse_frontmatter(leader_path.read_text())

        # Read worker-*.md files
        agents: list[AgentDefinition] = []
        for agent_file in sorted(template_dir.glob("worker-*.md")):
            agents.append(self.parse_agent_file(agent_file))

        if not agents:
            raise ValueError(
                f"Template '{template_key}' has no worker agent files (worker-*.md)"
            )

        # Read synthesis.md
        synthesis_path = template_dir / "synthesis.md"
        synthesis_prompt = synthesis_path.read_text() if synthesis_path.exists() else ""

        return LoadedTemplate(
            key=meta["key"],
            name=meta["name"],
            description=meta.get("description", ""),
            goal_template=meta.get("goal_template", ""),
            leader_prompt=leader_prompt,
            agents=agents,
            synthesis_prompt=synthesis_prompt,
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
            display_name=metadata.get(
                "displayName", metadata.get("name", path.stem)
            ),
            description=metadata.get("description", ""),
            tools=metadata.get("tools"),
            infer=metadata.get("infer", False),
            prompt_template=body,
        )
