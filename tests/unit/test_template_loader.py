"""Tests for TemplateLoader with YAML frontmatter parsing."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.swarm.template_loader import (
    AgentDefinition,
    LoadedTemplate,
    TemplateLoader,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_template_dir(
    tmp_path: Path,
    key: str = "test-template",
    name: str = "Test Template",
    description: str = "A test template",
    goal_template: str = "Accomplish {goal}",
    leader_body: str = "You are the leader.",
    leader_frontmatter: dict | None = None,
    workers: list[dict] | None = None,
    synthesis: str | None = None,
) -> Path:
    """Create a minimal template directory structure under *tmp_path*."""
    tpl_dir = tmp_path / key
    tpl_dir.mkdir(parents=True, exist_ok=True)

    # _template.yaml
    meta = {
        "key": key,
        "name": name,
        "description": description,
        "goal_template": goal_template,
    }
    (tpl_dir / "_template.yaml").write_text(yaml.dump(meta))

    # leader.md
    fm = yaml.dump(leader_frontmatter) if leader_frontmatter else ""
    leader_content = f"---\n{fm}---\n{leader_body}" if fm or leader_body else ""
    if leader_content:
        (tpl_dir / "leader.md").write_text(leader_content)

    # worker files
    if workers is None:
        workers = [
            {
                "filename": "worker-alpha.md",
                "name": "alpha",
                "displayName": "Alpha Agent",
                "description": "First worker",
                "tools": ["tool_a", "tool_b"],
                "infer": False,
                "body": "You are {display_name} with {role}.",
            }
        ]
    for w in workers:
        fm_dict = {k: v for k, v in w.items() if k not in ("filename", "body")}
        content = f"---\n{yaml.dump(fm_dict)}---\n{w.get('body', '')}"
        (tpl_dir / w["filename"]).write_text(content)

    # synthesis.md
    if synthesis is not None:
        (tpl_dir / "synthesis.md").write_text(synthesis)

    return tpl_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_parse_frontmatter_splits_yaml_and_body(self) -> None:
        content = "---\ntitle: hello\n---\nBody text here."
        metadata, body = TemplateLoader.parse_frontmatter(content)
        assert metadata == {"title": "hello"}
        assert body == "Body text here."

    def test_parse_frontmatter_no_frontmatter(self) -> None:
        content = "Just plain markdown with no front matter."
        metadata, body = TemplateLoader.parse_frontmatter(content)
        assert metadata == {}
        assert body == content


class TestParseAgentFile:
    def test_parse_agent_file_returns_agent_definition(self, tmp_path: Path) -> None:
        agent_file = tmp_path / "worker-alpha.md"
        agent_file.write_text(
            "---\n"
            "name: alpha\n"
            "displayName: Alpha Agent\n"
            "description: Does alpha things\n"
            "tools:\n  - tool_a\n  - tool_b\n"
            "infer: true\n"
            "---\n"
            "You are the alpha agent."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert isinstance(agent, AgentDefinition)
        assert agent.name == "alpha"
        assert agent.display_name == "Alpha Agent"
        assert agent.description == "Does alpha things"
        assert agent.tools == ["tool_a", "tool_b"]
        assert agent.infer is True
        assert agent.prompt_template == "You are the alpha agent."

    def test_parse_agent_file_defaults_display_name_to_name(self, tmp_path: Path) -> None:
        agent_file = tmp_path / "worker-beta.md"
        agent_file.write_text("---\nname: beta\ndescription: Beta worker\n---\nPrompt body.")
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.display_name == "beta"

    def test_tools_null_means_all_tools(self, tmp_path: Path) -> None:
        agent_file = tmp_path / "worker-gamma.md"
        agent_file.write_text("---\nname: gamma\ntools: null\n---\nBody.")
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.tools is None

    def test_agent_prompt_contains_placeholders(self, tmp_path: Path) -> None:
        agent_file = tmp_path / "worker-delta.md"
        agent_file.write_text("---\nname: delta\n---\nHello {display_name}, your {role} is important.")
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert "{display_name}" in agent.prompt_template
        assert "{role}" in agent.prompt_template


class TestLoad:
    def test_load_returns_loaded_template(self, tmp_path: Path) -> None:
        _create_template_dir(tmp_path)
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert isinstance(tpl, LoadedTemplate)
        assert tpl.key == "test-template"
        assert tpl.name == "Test Template"
        assert tpl.description == "A test template"
        assert tpl.goal_template == "Accomplish {goal}"
        assert len(tpl.agents) == 1

    def test_load_reads_leader_prompt_from_body(self, tmp_path: Path) -> None:
        _create_template_dir(
            tmp_path,
            leader_frontmatter={"role": "leader"},
            leader_body="Lead the team effectively.",
        )
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")
        assert tpl.leader_prompt == "Lead the team effectively."

    def test_load_reads_worker_agents(self, tmp_path: Path) -> None:
        workers = [
            {
                "filename": "worker-one.md",
                "name": "one",
                "displayName": "Worker One",
                "description": "First",
                "body": "Prompt one.",
            },
            {
                "filename": "worker-two.md",
                "name": "two",
                "displayName": "Worker Two",
                "description": "Second",
                "body": "Prompt two.",
            },
        ]
        _create_template_dir(tmp_path, workers=workers)
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert len(tpl.agents) == 2
        assert tpl.agents[0].name == "one"
        assert tpl.agents[1].name == "two"

    def test_load_reads_synthesis_prompt(self, tmp_path: Path) -> None:
        _create_template_dir(tmp_path, synthesis="Synthesize all findings.")
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")
        assert tpl.synthesis_prompt == "Synthesize all findings."

    def test_load_missing_template_raises_file_not_found(self, tmp_path: Path) -> None:
        loader = TemplateLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match="Template directory not found"):
            loader.load("nonexistent")

    def test_load_missing_template_yaml_raises_file_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "bad-template").mkdir()
        loader = TemplateLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match=r"Missing _template\.yaml"):
            loader.load("bad-template")

    def test_load_no_workers_raises_value_error(self, tmp_path: Path) -> None:
        _create_template_dir(tmp_path, workers=[])
        loader = TemplateLoader(tmp_path)
        with pytest.raises(ValueError, match="no worker agent files"):
            loader.load("test-template")


class TestMCPAndSkills:
    def test_load_parses_mcp_servers_yaml(self, tmp_path: Path) -> None:
        """Template with mcp-servers.yaml populates LoadedTemplate.mcp_servers."""
        _create_template_dir(tmp_path)
        mcp_config = {
            "servers": {
                "playwright": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp@latest"],
                    "tools": ["*"],
                },
            }
        }
        (tmp_path / "test-template" / "mcp-servers.yaml").write_text(yaml.dump(mcp_config))

        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert tpl.mcp_servers is not None
        assert "playwright" in tpl.mcp_servers
        assert tpl.mcp_servers["playwright"]["command"] == "npx"

    def test_load_detects_skills_dir(self, tmp_path: Path) -> None:
        """Template with skills/ subdirectory populates LoadedTemplate.skills_dir."""
        _create_template_dir(tmp_path)
        skills_dir = tmp_path / "test-template" / "skills" / "domain-expertise"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skill.md").write_text("---\nname: domain\n---\nDomain knowledge.")

        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert tpl.skills_dir is not None
        assert tpl.skills_dir.is_dir()

    def test_load_no_mcp_no_skills_defaults_to_none(self, tmp_path: Path) -> None:
        """Existing template without MCP or skills has None defaults."""
        _create_template_dir(tmp_path)
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert tpl.mcp_servers is None
        assert tpl.skills_dir is None


class TestMaxInstances:
    def test_parse_agent_file_reads_max_instances(self, tmp_path: Path) -> None:
        """Worker with maxInstances: 3 produces AgentDefinition with max_instances=3."""
        agent_file = tmp_path / "worker-scaler.md"
        agent_file.write_text(
            "---\n"
            "name: scaler\n"
            "displayName: Scaler Agent\n"
            "description: Scales out\n"
            "maxInstances: 3\n"
            "---\n"
            "You are a scalable worker."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.max_instances == 3

    def test_parse_agent_file_defaults_max_instances_to_1(self, tmp_path: Path) -> None:
        """Worker without maxInstances field defaults to max_instances=1."""
        agent_file = tmp_path / "worker-single.md"
        agent_file.write_text(
            "---\nname: single\ndisplayName: Single Agent\ndescription: Single instance\n---\nYou are a single worker."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.max_instances == 1

    def test_load_preserves_max_instances_in_agents(self, tmp_path: Path) -> None:
        """LoadedTemplate.agents carries parsed max_instances values through."""
        workers = [
            {
                "filename": "worker-scalable.md",
                "name": "scalable",
                "displayName": "Scalable Worker",
                "description": "Can scale",
                "maxInstances": 4,
                "body": "Scalable prompt.",
            },
            {
                "filename": "worker-fixed.md",
                "name": "fixed",
                "displayName": "Fixed Worker",
                "description": "Single instance",
                "body": "Fixed prompt.",
            },
        ]
        _create_template_dir(tmp_path, workers=workers)
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        scalable = next(a for a in tpl.agents if a.name == "scalable")
        fixed = next(a for a in tpl.agents if a.name == "fixed")
        assert scalable.max_instances == 4
        assert fixed.max_instances == 1


class TestPerWorkerSkills:
    def test_parse_agent_file_reads_skills_list(self, tmp_path: Path) -> None:
        """Worker with skills: [skill-a, skill-b] produces AgentDefinition.skills."""
        agent_file = tmp_path / "worker-skilled.md"
        agent_file.write_text(
            "---\n"
            "name: skilled\n"
            "displayName: Skilled Agent\n"
            "description: Has specific skills\n"
            "skills:\n  - azure-architect\n  - azure-security-expert\n"
            "---\n"
            "You are skilled."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.skills == ["azure-architect", "azure-security-expert"]

    def test_parse_agent_file_skills_null_is_none(self, tmp_path: Path) -> None:
        """Worker without skills field or with skills: null produces None."""
        agent_file = tmp_path / "worker-noskills.md"
        agent_file.write_text(
            "---\n"
            "name: noskills\n"
            "displayName: No Skills Agent\n"
            "description: No skills field\n"
            "---\n"
            "You have no skills config."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.skills is None

    def test_parse_agent_file_skills_wildcard(self, tmp_path: Path) -> None:
        """Worker with skills: ['*'] produces ['*']."""
        agent_file = tmp_path / "worker-wild.md"
        agent_file.write_text(
            "---\n"
            "name: wild\n"
            "displayName: Wild Agent\n"
            "description: All skills\n"
            'skills:\n  - "*"\n'
            "---\n"
            "You get all skills."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.skills == ["*"]

    def test_parse_agent_file_skills_empty_list(self, tmp_path: Path) -> None:
        """Worker with skills: [] produces empty list."""
        agent_file = tmp_path / "worker-empty.md"
        agent_file.write_text(
            "---\nname: empty\ndisplayName: Empty Agent\ndescription: No skills\nskills: []\n---\nYou get no skills."
        )
        agent = TemplateLoader.parse_agent_file(agent_file)
        assert agent.skills == []

    def test_load_enumerates_all_skill_names(self, tmp_path: Path) -> None:
        """Template with skills/ dir populates all_skill_names from frontmatter."""
        _create_template_dir(tmp_path)
        skills_dir = tmp_path / "test-template" / "skills"
        skill_a = skills_dir / "skill-a"
        skill_a.mkdir(parents=True)
        (skill_a / "skill.md").write_text("---\nname: Skill Alpha\n---\nContent A.")
        skill_b = skills_dir / "skill-b"
        skill_b.mkdir(parents=True)
        (skill_b / "skill.md").write_text("---\nname: Skill Beta\n---\nContent B.")

        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert tpl.all_skill_names == {"Skill Alpha", "Skill Beta"}
        assert tpl.skill_name_map == {"skill-a": "Skill Alpha", "skill-b": "Skill Beta"}

    def test_load_validates_unknown_skill_references(self, tmp_path: Path) -> None:
        """Worker referencing nonexistent skill raises ValueError."""
        workers = [
            {
                "filename": "worker-bad.md",
                "name": "bad",
                "displayName": "Bad Worker",
                "description": "References fake skill",
                "skills": ["nonexistent-skill"],
                "body": "Prompt.",
            },
        ]
        _create_template_dir(tmp_path, workers=workers)
        # Create skills dir with one real skill
        skills_dir = tmp_path / "test-template" / "skills" / "real-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skill.md").write_text("---\nname: real-skill\n---\nContent.")

        loader = TemplateLoader(tmp_path)
        with pytest.raises(ValueError, match="unknown skill"):
            loader.load("test-template")

    def test_load_backward_compat_no_skills_field(self, tmp_path: Path) -> None:
        """Existing templates without skills field or skills/ dir load fine."""
        _create_template_dir(tmp_path)
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")

        assert tpl.all_skill_names == set()
        assert tpl.skill_name_map == {}
        # Agent should have skills=None
        assert tpl.agents[0].skills is None


class TestQAFlag:
    def test_load_parses_qa_enabled_from_leader(self, tmp_path: Path) -> None:
        """Leader with qa: true in frontmatter produces LoadedTemplate.qa_enabled=True."""
        _create_template_dir(
            tmp_path,
            leader_frontmatter={"qa": True},
            leader_body="You are the leader.\n\n## Q&A Questions\nAsk about scale.",
        )
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")
        assert tpl.qa_enabled is True

    def test_load_qa_disabled_by_default(self, tmp_path: Path) -> None:
        """Leader without qa field produces LoadedTemplate.qa_enabled=False."""
        _create_template_dir(tmp_path)
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")
        assert tpl.qa_enabled is False

    def test_load_captures_leader_prompt_for_qa(self, tmp_path: Path) -> None:
        """Leader prompt is available for Q&A session regardless of qa flag."""
        _create_template_dir(
            tmp_path,
            leader_frontmatter={"qa": True},
            leader_body="You are the leader.\n\n## Q&A\nAsk about enterprise size.",
        )
        loader = TemplateLoader(tmp_path)
        tpl = loader.load("test-template")
        assert "enterprise size" in tpl.leader_prompt


class TestLoadAllAndListAvailable:
    def test_load_all_returns_multiple_templates(self, tmp_path: Path) -> None:
        _create_template_dir(tmp_path, key="tpl-a", name="Template A")
        _create_template_dir(tmp_path, key="tpl-b", name="Template B")
        loader = TemplateLoader(tmp_path)
        result = loader.load_all()

        assert len(result) == 2
        assert "tpl-a" in result
        assert "tpl-b" in result
        assert result["tpl-a"].name == "Template A"
        assert result["tpl-b"].name == "Template B"

    def test_list_available_returns_summaries(self, tmp_path: Path) -> None:
        _create_template_dir(tmp_path, key="tpl-x", name="X", description="Desc X")
        _create_template_dir(tmp_path, key="tpl-y", name="Y", description="Desc Y")
        loader = TemplateLoader(tmp_path)
        summaries = loader.list_available()

        assert len(summaries) == 2
        assert summaries[0] == {"key": "tpl-x", "name": "X", "description": "Desc X"}
        assert summaries[1] == {"key": "tpl-y", "name": "Y", "description": "Desc Y"}


# ---------------------------------------------------------------------------
# System preamble tests
# ---------------------------------------------------------------------------


class TestSystemPreamble:
    def test_loader_reads_system_prompt_file(self, tmp_path: Path) -> None:
        """TemplateLoader reads system-prompt.md from the templates directory."""
        (tmp_path / "system-prompt.md").write_text("You MUST call task_update and inbox_send")
        loader = TemplateLoader(tmp_path)
        assert "task_update" in loader.system_preamble
        assert "inbox_send" in loader.system_preamble

    def test_loader_falls_back_when_no_system_prompt(self, tmp_path: Path) -> None:
        """If system-prompt.md doesn't exist, system_preamble is empty string."""
        loader = TemplateLoader(tmp_path)
        assert loader.system_preamble == ""

    def test_real_system_prompt_contains_mandatory_tools(self) -> None:
        """The actual src/templates/system-prompt.md contains coordination tools."""
        loader = TemplateLoader(Path("src/templates"))
        assert "task_update" in loader.system_preamble
        assert "inbox_send" in loader.system_preamble
        assert "inbox_receive" in loader.system_preamble
        assert "task_list" in loader.system_preamble

    def test_system_tools_loaded_from_frontmatter(self) -> None:
        """system_tools list is read from system-prompt.md frontmatter."""
        loader = TemplateLoader(Path("src/templates"))
        assert loader.system_tools == ["task_update", "inbox_send", "inbox_receive", "task_list"]

    def test_system_tools_empty_when_no_file(self, tmp_path: Path) -> None:
        """system_tools is empty list when no system-prompt.md."""
        loader = TemplateLoader(tmp_path)
        assert loader.system_tools == []
