"""TDD tests for the templates system and SwarmConfig."""

from __future__ import annotations

from backend.config import SwarmConfig
from backend.swarm.templates import (
    TEMPLATES,
    format_goal,
    get_template,
    list_templates,
)


# ---------------------------------------------------------------------------
# Template listing
# ---------------------------------------------------------------------------


def test_list_templates_returns_builtin() -> None:
    """list_templates returns the built-in templates with correct keys."""
    result = list_templates()
    assert len(result) == 2
    keys = {t["key"] for t in result}
    assert keys == {"deep-research", "warehouse-optimizer"}


# ---------------------------------------------------------------------------
# Template lookup
# ---------------------------------------------------------------------------


def test_get_template_returns_correct_template() -> None:
    """get_template('deep-research') returns the Deep Research Team."""
    tmpl = get_template("deep-research")
    assert tmpl is not None
    assert tmpl.name == "Deep Research Team"


def test_get_template_returns_none_for_unknown() -> None:
    """get_template('unknown') returns None."""
    assert get_template("unknown") is None


# ---------------------------------------------------------------------------
# Goal formatting
# ---------------------------------------------------------------------------


def test_format_goal_with_valid_template() -> None:
    """format_goal inserts user_input into the template."""
    goal = format_goal("deep-research", "the impact of AI on healthcare")
    assert "the impact of AI on healthcare" in goal
    assert "deep research team" in goal.lower()


def test_format_goal_with_unknown_template() -> None:
    """format_goal returns raw user_input when template is not found."""
    raw = "just do this thing"
    assert format_goal("nonexistent", raw) == raw


# ---------------------------------------------------------------------------
# Template content assertions
# ---------------------------------------------------------------------------


def test_all_templates_have_user_input_placeholder() -> None:
    """Every template's goal_template contains {user_input}."""
    for key, tmpl in TEMPLATES.items():
        assert "{user_input}" in tmpl.goal_template, f"{key} missing {{user_input}}"


def test_warehouse_optimizer_template_has_blocked_by() -> None:
    """The warehouse-optimizer goal mentions 'blocked by'."""
    goal = format_goal("warehouse-optimizer", "optimize the fulfillment center")
    assert "blocked by" in goal.lower()


# ---------------------------------------------------------------------------
# SwarmConfig defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    """SwarmConfig() has the expected default values."""
    cfg = SwarmConfig()
    assert cfg.model == "gemini-3-pro-preview"
    assert cfg.max_rounds == 3
    assert cfg.timeout == 1800.0
    assert cfg.max_workers == 5
