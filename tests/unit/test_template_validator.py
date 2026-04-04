"""TDD tests for template file validation — RED first, then GREEN."""

from __future__ import annotations

from backend.swarm.template_validator import validate_template_file


class TestTemplateValidator:
    def test_valid_worker_file_passes(self) -> None:
        """A well-formed worker file with all required fields passes validation."""
        content = """---
name: researcher
displayName: Primary Researcher
description: Conducts in-depth research
tools:
  - task_update
  - inbox_send
---

You are a research specialist. Investigate the assigned topic thoroughly.
"""
        result = validate_template_file("worker-researcher.md", content)
        assert result.valid is True
        assert result.errors == []

    def test_missing_frontmatter_fails(self) -> None:
        """A file without --- frontmatter delimiters fails."""
        content = "Just plain text without frontmatter."
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        assert any("frontmatter" in e.message.lower() for e in result.errors)

    def test_invalid_yaml_fails(self) -> None:
        """Malformed YAML in frontmatter returns parse error with line number."""
        content = """---
name: test
bad yaml: [unterminated
---

Body text.
"""
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        assert any("yaml" in e.message.lower() or "parse" in e.message.lower() for e in result.errors)
        # Should include a line number
        assert any(e.line is not None for e in result.errors)

    def test_missing_required_fields_fails(self) -> None:
        """Worker file missing required frontmatter fields fails."""
        content = """---
name: test
---

Body text.
"""
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        # Missing displayName and description
        error_messages = " ".join(e.message.lower() for e in result.errors)
        assert "displayname" in error_messages or "display" in error_messages

    def test_unknown_tool_name_fails(self) -> None:
        """Tools list with unknown tool names fails validation."""
        content = """---
name: test
displayName: Test Worker
description: A test worker
tools:
  - task_update
  - unknown_tool
  - hacker_tool
---

Body text.
"""
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        error_messages = " ".join(e.message for e in result.errors)
        assert "unknown_tool" in error_messages or "hacker_tool" in error_messages

    def test_template_yaml_missing_user_input_placeholder_fails(self) -> None:
        """_template.yaml goal_template without {user_input} placeholder fails."""
        content = """---
key: test-template
name: Test Template
description: A test template
goal_template: "Do something without any placeholder"
---
"""
        result = validate_template_file("_template.yaml", content)
        assert result.valid is False
        assert any("user_input" in e.message for e in result.errors)

    def test_leader_with_empty_body_fails(self) -> None:
        """leader.md with empty body after frontmatter fails."""
        content = """---
name: leader
---

"""
        result = validate_template_file("leader.md", content)
        assert result.valid is False
        assert any("body" in e.message.lower() or "empty" in e.message.lower() for e in result.errors)

    # -----------------------------------------------------------------------
    # maxInstances validation
    # -----------------------------------------------------------------------

    def test_valid_worker_with_max_instances_passes(self) -> None:
        """Worker with maxInstances: 3 passes validation."""
        content = """---
name: scaler
displayName: Scalable Worker
description: Scales out for parallel tasks
maxInstances: 3
tools:
  - task_update
---

You are a scalable worker.
"""
        result = validate_template_file("worker-scaler.md", content)
        assert result.valid is True

    def test_max_instances_zero_fails(self) -> None:
        """maxInstances: 0 fails validation."""
        content = """---
name: broken
displayName: Broken Worker
description: Zero instances
maxInstances: 0
---

Body text.
"""
        result = validate_template_file("worker-broken.md", content)
        assert result.valid is False
        assert any("maxinstances" in e.message.lower() for e in result.errors)

    def test_max_instances_negative_fails(self) -> None:
        """maxInstances: -1 fails validation."""
        content = """---
name: broken
displayName: Broken Worker
description: Negative instances
maxInstances: -1
---

Body text.
"""
        result = validate_template_file("worker-broken.md", content)
        assert result.valid is False
        assert any("maxinstances" in e.message.lower() for e in result.errors)

    def test_max_instances_non_integer_fails(self) -> None:
        """maxInstances: 'three' fails validation."""
        content = """---
name: broken
displayName: Broken Worker
description: String instances
maxInstances: three
---

Body text.
"""
        result = validate_template_file("worker-broken.md", content)
        assert result.valid is False
        assert any("maxinstances" in e.message.lower() for e in result.errors)

    def test_max_instances_float_fails(self) -> None:
        """maxInstances: 2.5 fails validation."""
        content = """---
name: broken
displayName: Broken Worker
description: Float instances
maxInstances: 2.5
---

Body text.
"""
        result = validate_template_file("worker-broken.md", content)
        assert result.valid is False
        assert any("maxinstances" in e.message.lower() for e in result.errors)

    def test_worker_without_max_instances_passes(self) -> None:
        """Existing workers without maxInstances still pass (backward compat)."""
        content = """---
name: classic
displayName: Classic Worker
description: No maxInstances field
tools:
  - task_update
---

Body text.
"""
        result = validate_template_file("worker-classic.md", content)
        assert result.valid is True

    # -----------------------------------------------------------------------
    # skills validation
    # -----------------------------------------------------------------------

    def test_skills_field_must_be_list(self) -> None:
        """Worker with skills: 'not-a-list' fails validation."""
        content = """---
name: broken
displayName: Broken Worker
description: Bad skills
skills: not-a-list
---

Body text.
"""
        result = validate_template_file("worker-broken.md", content)
        assert result.valid is False
        assert any("skills" in e.message.lower() for e in result.errors)

    def test_skills_entries_must_be_strings(self) -> None:
        """Worker with skills: [123] fails validation."""
        content = """---
name: broken
displayName: Broken Worker
description: Numeric skills
skills:
  - 123
---

Body text.
"""
        result = validate_template_file("worker-broken.md", content)
        assert result.valid is False
        assert any("skill" in e.message.lower() and "string" in e.message.lower() for e in result.errors)

    def test_valid_skills_field_passes(self) -> None:
        """Worker with skills: [azure-architect] passes validation."""
        content = """---
name: valid
displayName: Valid Worker
description: Good skills
skills:
  - azure-architect
  - entra-expert
tools:
  - task_update
---

Body text.
"""
        result = validate_template_file("worker-valid.md", content)
        assert result.valid is True

    def test_valid_template_yaml_passes(self) -> None:
        """A well-formed _template.yaml passes validation."""
        content = """---
key: deep-research
name: Deep Research Team
description: Multi-perspective research team
goal_template: "Assemble a research team to investigate: {user_input}"
---
"""
        result = validate_template_file("_template.yaml", content)
        assert result.valid is True
        assert result.errors == []
