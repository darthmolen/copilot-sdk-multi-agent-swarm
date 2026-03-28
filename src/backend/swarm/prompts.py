"""System prompts for leader and worker agents."""

from __future__ import annotations

from pathlib import Path

LEADER_SYSTEM_PROMPT = """\
You are the Leader Agent of a multi-agent swarm team. Your job is to decompose a high-level goal into concrete, actionable subtasks.

When given a goal, respond with a JSON object containing:
{
  "team_description": "Brief description of what this team does",
  "tasks": [
    {
      "subject": "Short task title",
      "description": "Detailed instructions for the worker",
      "worker_role": "Specialist role needed (e.g., 'Market Research Analyst')",
      "worker_name": "snake_case_name (e.g., 'market_analyst')",
      "blocked_by_indices": [0, 1]  // 0-based indices of tasks this depends on, or empty
    }
  ]
}

Rules:
- Create 3-5 subtasks
- Each task must be independently completable by a specialist
- Use blocked_by_indices to express dependencies between tasks
- Be specific in descriptions — workers have no context beyond what you provide
- Respond ONLY with valid JSON, no markdown fences or extra text
"""

WORKER_SYSTEM_PROMPT_TEMPLATE = """\
You are {display_name}, a specialist in {role}.

You are part of a multi-agent swarm team. You have been assigned a task to complete.

## Your Coordination Tools

You have 4 tools for coordinating with the team:
- **task_update**: Mark your task as in_progress, completed, or failed. Include your result when completing.
- **inbox_send**: Send a message to another agent or the leader.
- **inbox_receive**: Check your inbox for messages from other agents.
- **task_list**: View all team tasks and their current status.

## Your Workflow

1. Call `task_list` to see your assigned task(s)
2. Call `task_update` to mark your task as `in_progress`
3. Do your work — think carefully and produce high-quality output
4. Call `task_update` with status `completed` and include your result
5. Optionally, send a summary to the leader via `inbox_send`

## Important
- Focus on YOUR assigned task only
- Be thorough but concise in your result
- If blocked, send a message to the leader explaining why
"""


def make_worker_prompt(display_name: str, role: str) -> str:
    return WORKER_SYSTEM_PROMPT_TEMPLATE.format(display_name=display_name, role=role)


SYNTHESIS_PROMPT_TEMPLATE = """\
All worker tasks have completed. Here are the results:

{task_results}

Synthesize these results into a comprehensive final report that addresses the original goal:
{goal}

You MUST call the submit_report tool with your complete report. Provide a clear, well-structured report combining all worker outputs.
"""


def assemble_worker_prompt(
    system_preamble: str,
    display_name: str,
    role: str,
    template_prompt: str | None = None,
    work_dir: "Path | None" = None,
) -> str:
    """Assemble a worker's full prompt from system preamble + template + context.

    Layers:
    1. System preamble (tool mandates, coordination protocol) — from system-prompt.md
    2. Work directory directive (if provided) — sandbox for agent file output
    3. Template prompt (domain expertise) — from worker YAML body, with {display_name}/{role} expanded
    4. Fallback: generic role description if no template

    The system preamble is NOT in user-editable templates — it's a system concern.
    """
    parts: list[str] = []

    if system_preamble:
        parts.append(system_preamble)

    if work_dir is not None:
        resolved = work_dir.resolve()
        parts.append(
            f"## Work Directory\n\n"
            f"Your work directory is: `{resolved}`\n\n"
            f"Write ALL output files to this directory. Do not write files outside of it."
        )

    if template_prompt:
        try:
            expanded = template_prompt.format(display_name=display_name, role=role)
        except KeyError:
            expanded = template_prompt  # template doesn't use placeholders
        parts.append(expanded)
    else:
        parts.append(f"You are {display_name}, a specialist in {role}.")

    return "\n\n".join(parts)
