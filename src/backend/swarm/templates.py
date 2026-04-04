"""Pre-built swarm templates that format user input into leader goal prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SwarmTemplate:
    key: str
    name: str
    description: str
    goal_template: str  # f-string template with {user_input} placeholder


TEMPLATES: dict[str, SwarmTemplate] = {
    "deep-research": SwarmTemplate(
        key="deep-research",
        name="Deep Research Team",
        description="A multi-perspective research team that investigates a topic from different angles",
        goal_template=(
            "Assemble a deep research team to investigate: {user_input}\n\n"
            "Create specialists for: primary source research, contrarian/skeptical analysis, "
            "quantitative data gathering, and synthesis. "
            "All research tasks can run in parallel. "
            "The synthesis task should be blocked by all research tasks."
        ),
    ),
    "warehouse-optimizer": SwarmTemplate(
        key="warehouse-optimizer",
        name="Warehouse Optimization Team",
        description="A team that analyzes and optimizes warehouse operations, logistics, and inventory",
        goal_template=(
            "Assemble a warehouse optimization team to: {user_input}\n\n"
            "Create specialists for: inventory analysis, layout/flow optimization, "
            "demand forecasting, and implementation planning. "
            "Inventory analysis and demand forecasting can run in parallel. "
            "Layout optimization should be blocked by inventory analysis. "
            "Implementation planning should be blocked by all other tasks."
        ),
    ),
}


def get_template(key: str) -> SwarmTemplate | None:
    """Return a template by key, or None if not found."""
    return TEMPLATES.get(key)


def list_templates() -> list[dict]:
    """Return summary dicts for all templates (used by the API)."""
    return [{"key": t.key, "name": t.name, "description": t.description} for t in TEMPLATES.values()]


def format_goal(template_key: str, user_input: str) -> str:
    """Format user input using a template. Returns raw user_input if template not found."""
    template = TEMPLATES.get(template_key)
    if template is None:
        return user_input
    return template.goal_template.format(user_input=user_input)
