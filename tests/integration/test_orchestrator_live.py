"""Orchestrator integration test -- leader plan decomposition against real LLM.

This is the single most critical integration point: verifying that the leader
agent, given a goal and our system prompt, returns valid JSON with a "tasks"
array that the orchestrator can parse.

Requires a live copilot-cli process and real LLM API calls.
"""

import json

import pytest

from copilot import CopilotClient
from copilot.session import PermissionHandler

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# ---------------------------------------------------------------------------
# Leader system prompt (simplified version for testing)
# ---------------------------------------------------------------------------

LEADER_SYSTEM_PROMPT = """\
You are a task-planning leader agent in a multi-agent swarm.

Given a goal, decompose it into a list of tasks that worker agents can execute.

IMPORTANT: You MUST respond with ONLY a valid JSON object (no markdown fences,
no extra text). The JSON must have this exact structure:

{
  "tasks": [
    {
      "id": "t-1",
      "subject": "short title",
      "description": "what to do",
      "worker_role": "coder",
      "blocked_by": []
    }
  ]
}

Rules:
- Each task needs a unique id starting with "t-"
- worker_role must be one of: coder, reviewer, researcher
- blocked_by is a list of task ids that must complete first (can be empty)
- Keep the plan simple: 2-4 tasks maximum
"""


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


async def test_leader_decomposes_goal_into_tasks(copilot_client: CopilotClient):
    """Send a goal to the leader agent and verify it produces valid task JSON."""
    session = await copilot_client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        system_message={"content": LEADER_SYSTEM_PROMPT},
    )

    try:
        response = await session.send_and_wait(
            "Goal: Write a Python function that computes Fibonacci numbers efficiently.",
            timeout=120,
        )

        assert response is not None, "No response from leader session"

        content = getattr(response.data, "content", "") or ""
        assert len(content.strip()) > 0, "Leader returned empty content"

        # Strip markdown fences if present (LLMs sometimes wrap JSON).
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        plan = json.loads(cleaned)

        assert "tasks" in plan, f"Plan missing 'tasks' key. Got keys: {list(plan.keys())}"
        tasks = plan["tasks"]
        assert isinstance(tasks, list), f"Expected tasks to be a list, got {type(tasks)}"
        assert len(tasks) >= 1, "Expected at least one task in the plan"

        # Validate each task has required fields.
        for task in tasks:
            assert "id" in task, f"Task missing 'id': {task}"
            assert "subject" in task or "description" in task, (
                f"Task missing subject/description: {task}"
            )
            assert "worker_role" in task, f"Task missing 'worker_role': {task}"

    finally:
        await session.disconnect()
