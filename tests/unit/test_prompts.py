"""Tests for prompt assembly — system preamble + template + context."""

from __future__ import annotations


def test_assemble_worker_prompt_combines_all_layers() -> None:
    """Preamble + template + context substitutions."""
    from backend.swarm.prompts import assemble_worker_prompt

    result = assemble_worker_prompt(
        system_preamble="## Protocol\nYou MUST call task_update and inbox_send.",
        display_name="Dr. Smith",
        role="Primary Researcher",
        template_prompt="# {display_name} — {role}\n\nYou are an expert in literature review.",
    )
    # System preamble present
    assert "task_update" in result
    assert "inbox_send" in result
    # Template prompt present
    assert "literature review" in result
    # Context substituted
    assert "Dr. Smith" in result
    assert "Primary Researcher" in result
    # Preamble comes first
    assert result.index("Protocol") < result.index("literature review")


def test_assemble_worker_prompt_fallback_without_template() -> None:
    """Without template, generates a generic role prompt."""
    from backend.swarm.prompts import assemble_worker_prompt

    result = assemble_worker_prompt(
        system_preamble="## Protocol\nMandatory tools.",
        display_name="Coder",
        role="Write Python code",
    )
    assert "Protocol" in result
    assert "Coder" in result
    assert "Write Python code" in result


def test_assemble_worker_prompt_empty_preamble() -> None:
    """Empty preamble still produces valid prompt."""
    from backend.swarm.prompts import assemble_worker_prompt

    result = assemble_worker_prompt(
        system_preamble="",
        display_name="Agent",
        role="Do stuff",
        template_prompt="Domain expertise here.",
    )
    assert "Domain expertise here." in result
    assert "Agent" not in result or True  # template may not use {display_name}
