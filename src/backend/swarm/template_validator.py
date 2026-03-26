"""Pure template file validation.

validate_template_file(filename, content) -> ValidationResult
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml


KNOWN_TOOLS = {"task_update", "inbox_send", "inbox_receive", "task_list"}

TEMPLATE_YAML_REQUIRED = {"key", "name", "description", "goal_template"}
WORKER_REQUIRED = {"name", "displayName", "description"}


@dataclass
class ValidationError:
    message: str
    line: int | None = None


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)


def _parse_frontmatter(content: str) -> tuple[dict | None, str, ValidationError | None]:
    """Extract YAML frontmatter and body from a markdown/yaml file.

    Returns (frontmatter_dict, body, error_or_none).
    """
    lines = content.split("\n")

    # Find opening ---
    if not lines or lines[0].strip() != "---":
        return None, content, ValidationError("Missing frontmatter: file must start with ---", line=1)

    # Find closing ---
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        return None, content, ValidationError("Missing frontmatter: no closing --- found", line=1)

    yaml_text = "\n".join(lines[1:close_idx])
    body = "\n".join(lines[close_idx + 1:])

    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return None, body, ValidationError("Frontmatter must be a YAML mapping", line=1)
        return data, body, None
    except yaml.YAMLError as e:
        line_num = None
        if hasattr(e, "problem_mark") and e.problem_mark is not None:
            line_num = e.problem_mark.line + 2  # +1 for 0-index, +1 for opening ---
        return None, body, ValidationError(f"Invalid YAML: {e}", line=line_num)


def validate_template_file(filename: str, content: str) -> ValidationResult:
    """Validate a template file by filename convention.

    - _template.yaml: required fields key, name, description, goal_template;
      goal_template must contain {user_input}
    - worker-*.md: required frontmatter fields name, displayName, description
    - leader.md / synthesis.md: must have non-empty body after frontmatter
    - tools list (if present) only contains known tool names
    """
    errors: list[ValidationError] = []

    frontmatter, body, parse_error = _parse_frontmatter(content)
    if parse_error:
        errors.append(parse_error)
        return ValidationResult(valid=False, errors=errors)

    assert frontmatter is not None  # parse_error was None so frontmatter exists

    # _template.yaml validation
    if filename == "_template.yaml":
        for field_name in sorted(TEMPLATE_YAML_REQUIRED):
            if field_name not in frontmatter:
                errors.append(ValidationError(f"Missing required field: {field_name}"))
        goal_template = frontmatter.get("goal_template", "")
        if isinstance(goal_template, str) and "{user_input}" not in goal_template:
            errors.append(ValidationError("goal_template must contain {user_input} placeholder"))

    # Worker file validation
    elif filename.startswith("worker-") and filename.endswith(".md"):
        for field_name in sorted(WORKER_REQUIRED):
            if field_name not in frontmatter:
                errors.append(ValidationError(f"Missing required field: {field_name}"))

    # Leader/synthesis validation
    elif filename in ("leader.md", "synthesis.md"):
        if not body.strip():
            errors.append(ValidationError(f"{filename} must have non-empty body after frontmatter"))

    # Tools validation (applies to all files with tools)
    tools = frontmatter.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            errors.append(ValidationError("tools must be a list"))
        else:
            unknown = set(tools) - KNOWN_TOOLS
            for tool_name in sorted(unknown):
                errors.append(
                    ValidationError(
                        f"Unknown tool: {tool_name}. Known tools: {', '.join(sorted(KNOWN_TOOLS))}"
                    )
                )

    return ValidationResult(valid=len(errors) == 0, errors=errors)
