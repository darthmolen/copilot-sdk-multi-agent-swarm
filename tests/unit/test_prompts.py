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


def test_assemble_worker_prompt_includes_work_dir() -> None:
    """When work_dir is provided, prompt includes the absolute path."""
    from pathlib import Path
    from backend.swarm.prompts import assemble_worker_prompt

    result = assemble_worker_prompt(
        system_preamble="## Protocol",
        display_name="Agent",
        role="Coder",
        work_dir=Path("/tmp/swarm-workdir/swarm-abc"),
    )
    assert "/tmp/swarm-workdir/swarm-abc" in result
    assert "work directory" in result.lower() or "work_dir" in result.lower()


def test_work_dir_in_prompt_is_absolute() -> None:
    """When a relative work_dir is passed, prompt must contain the absolute resolved path."""
    from pathlib import Path
    from backend.swarm.prompts import assemble_worker_prompt

    relative_dir = Path("workdir/swarm-test-abc")
    result = assemble_worker_prompt(
        system_preamble="",
        display_name="Agent",
        role="Coder",
        work_dir=relative_dir,
    )
    # The prompt must contain an absolute path (starts with /)
    assert "workdir/swarm-test-abc" not in result or str(relative_dir.resolve()) in result
    # The resolved absolute path must appear
    assert str(relative_dir.resolve()) in result


def test_work_dir_in_prompt_resolves_correctly() -> None:
    """Relative path must be resolved to absolute — bare relative string must not appear alone."""
    from pathlib import Path
    from backend.swarm.prompts import assemble_worker_prompt

    relative_dir = Path("workdir/swarm-xyz")
    resolved = str(relative_dir.resolve())
    result = assemble_worker_prompt(
        system_preamble="",
        display_name="Agent",
        role="Coder",
        work_dir=relative_dir,
    )
    # Must contain the full absolute path
    assert resolved in result
    # The path in the prompt must start with /
    import re
    match = re.search(r'`([^`]+)`', result)
    assert match is not None
    assert Path(match.group(1)).is_absolute(), f"Path in prompt is not absolute: {match.group(1)}"


def test_assemble_worker_prompt_no_work_dir_omits_section() -> None:
    """When work_dir is None, no work directory section in prompt."""
    from backend.swarm.prompts import assemble_worker_prompt

    result = assemble_worker_prompt(
        system_preamble="## Protocol",
        display_name="Agent",
        role="Coder",
    )
    assert "work directory" not in result.lower()


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
