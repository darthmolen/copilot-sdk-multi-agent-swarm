"""TDD tests for template file validation — RED first, then GREEN."""

from __future__ import annotations

import pytest

from backend.swarm.template_validator import validate_template_file, ValidationResult


class TestTemplateValidator:
    def test_valid_worker_file_passes(self) -> None:
        """A well-formed worker file with all required fields passes validation."""
        content = '''---
name: researcher
displayName: Primary Researcher
description: Conducts in-depth research
tools:
  - task_update
  - inbox_send
---

You are a research specialist. Investigate the assigned topic thoroughly.
'''
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
        content = '''---
name: test
bad yaml: [unterminated
---

Body text.
'''
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        assert any("yaml" in e.message.lower() or "parse" in e.message.lower() for e in result.errors)
        # Should include a line number
        assert any(e.line is not None for e in result.errors)

    def test_missing_required_fields_fails(self) -> None:
        """Worker file missing required frontmatter fields fails."""
        content = '''---
name: test
---

Body text.
'''
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        # Missing displayName and description
        error_messages = " ".join(e.message.lower() for e in result.errors)
        assert "displayname" in error_messages or "display" in error_messages

    def test_unknown_tool_name_fails(self) -> None:
        """Tools list with unknown tool names fails validation."""
        content = '''---
name: test
displayName: Test Worker
description: A test worker
tools:
  - task_update
  - unknown_tool
  - hacker_tool
---

Body text.
'''
        result = validate_template_file("worker-test.md", content)
        assert result.valid is False
        error_messages = " ".join(e.message for e in result.errors)
        assert "unknown_tool" in error_messages or "hacker_tool" in error_messages

    def test_template_yaml_missing_user_input_placeholder_fails(self) -> None:
        """_template.yaml goal_template without {user_input} placeholder fails."""
        content = '''---
key: test-template
name: Test Template
description: A test template
goal_template: "Do something without any placeholder"
---
'''
        result = validate_template_file("_template.yaml", content)
        assert result.valid is False
        assert any("user_input" in e.message for e in result.errors)

    def test_leader_with_empty_body_fails(self) -> None:
        """leader.md with empty body after frontmatter fails."""
        content = '''---
name: leader
---

'''
        result = validate_template_file("leader.md", content)
        assert result.valid is False
        assert any("body" in e.message.lower() or "empty" in e.message.lower() for e in result.errors)

    def test_valid_template_yaml_passes(self) -> None:
        """A well-formed _template.yaml passes validation."""
        content = '''---
key: deep-research
name: Deep Research Team
description: Multi-perspective research team
goal_template: "Assemble a research team to investigate: {user_input}"
---
'''
        result = validate_template_file("_template.yaml", content)
        assert result.valid is True
        assert result.errors == []
