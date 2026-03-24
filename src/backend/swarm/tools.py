"""Swarm tool abstractions and factory for agent-callable tools.

Provides a lightweight Tool protocol compatible with copilot-sdk's define_tool,
and a factory that creates closure-bound tools for task and inbox operations.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from pydantic import BaseModel, Field, ValidationError

from backend.swarm.inbox_system import InboxSystem
from backend.swarm.task_board import TaskBoard

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Tool protocol (matches copilot-sdk shape)
# ---------------------------------------------------------------------------


@dataclass
class ToolInvocation:
    session_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: Any = None


@dataclass
class ToolResult:
    text_result_for_llm: str = ""
    result_type: str = "success"
    error: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[[ToolInvocation], Awaitable[ToolResult]]
    parameters: dict[str, Any] | None = None
    skip_permission: bool = False
    overrides_built_in_tool: bool = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_swarm_tools(
    agent_name: str,
    task_board: TaskBoard,
    inbox: InboxSystem,
    event_callback: Callable[..., Any] | None = None,
) -> list[Tool]:
    """Create the four standard swarm tools, closure-capturing shared state.

    Returns a list of Tool instances for: task_update, inbox_send,
    inbox_receive, task_list.
    """

    # -- task_update --------------------------------------------------------

    async def _task_update(invocation: ToolInvocation) -> ToolResult:
        args: dict[str, Any] = invocation.arguments or {}
        task_id: str = args["task_id"]
        status: str = args["status"]
        result: str = args.get("result", "")

        task = await task_board.update_status(task_id, status, result)

        if event_callback is not None:
            cb_result = event_callback(
                {
                    "event": "task_update",
                    "agent": agent_name,
                    "task_id": task_id,
                    "status": status,
                    "result": result,
                }
            )
            if asyncio.iscoroutine(cb_result):
                await cb_result

        return ToolResult(
            text_result_for_llm=json.dumps({"ok": True, "task_id": task_id}),
        )

    # -- inbox_send ---------------------------------------------------------

    async def _inbox_send(invocation: ToolInvocation) -> ToolResult:
        args: dict[str, Any] = invocation.arguments or {}
        to: str = args["to"]
        message: str = args["message"]

        await inbox.send(agent_name, to, message)

        if event_callback is not None:
            cb_result = event_callback({
                "event": "inbox.message",
                "sender": agent_name,
                "recipient": to,
                "content": message,
            })
            if asyncio.iscoroutine(cb_result):
                await cb_result

        return ToolResult(
            text_result_for_llm=json.dumps({"ok": True, "sent_to": to}),
        )

    # -- inbox_receive ------------------------------------------------------

    async def _inbox_receive(invocation: ToolInvocation) -> ToolResult:
        messages = await inbox.receive(agent_name)

        payload = {
            "messages": [
                {
                    "sender": m.sender,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in messages
            ]
        }

        return ToolResult(
            text_result_for_llm=json.dumps(payload),
        )

    # -- task_list ----------------------------------------------------------

    async def _task_list(invocation: ToolInvocation) -> ToolResult:
        args: dict[str, Any] = invocation.arguments or {}
        owner: str | None = args.get("owner")

        tasks = await task_board.get_tasks(owner=owner)

        payload = {"tasks": [t.to_dict() for t in tasks]}

        return ToolResult(
            text_result_for_llm=json.dumps(payload),
        )

    # -- assemble -----------------------------------------------------------

    return [
        Tool(
            name="task_update",
            description="Update the status of a task on the task board.",
            handler=_task_update,
            parameters={
                "task_id": {"type": "string", "required": True},
                "status": {"type": "string", "required": True},
                "result": {"type": "string", "required": False},
            },
            skip_permission=True,
        ),
        Tool(
            name="inbox_send",
            description="Send a message to another agent's inbox.",
            handler=_inbox_send,
            parameters={
                "to": {"type": "string", "required": True},
                "message": {"type": "string", "required": True},
            },
            skip_permission=True,
        ),
        Tool(
            name="inbox_receive",
            description="Receive and clear all messages from your inbox.",
            handler=_inbox_receive,
            parameters=None,
            skip_permission=True,
        ),
        Tool(
            name="task_list",
            description="List tasks on the task board, optionally filtered by owner.",
            handler=_task_list,
            parameters={
                "owner": {"type": "string", "required": False},
            },
            skip_permission=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Leader plan / synthesis tools (structured output via function calling)
# ---------------------------------------------------------------------------


class TaskPlan(BaseModel):
    """Schema for a single task in the leader's plan."""

    subject: str
    description: str
    worker_role: str
    worker_name: str
    blocked_by_indices: list[int] = Field(default_factory=list)


class SwarmPlan(BaseModel):
    """Schema the leader submits via the create_plan tool."""

    team_description: str
    tasks: list[TaskPlan]


class SwarmReport(BaseModel):
    """Schema the leader submits via the submit_report tool."""

    report: str


def create_plan_tool(plan_holder: list[dict[str, Any]]) -> Tool:
    """Return a tool the leader calls to submit its decomposed plan.

    The plan is captured in *plan_holder* (mutated in place) so the
    orchestrator can read it after the leader's turn ends.
    """

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        args = invocation.arguments or {}
        try:
            plan = SwarmPlan.model_validate(args)
            plan_holder.append(plan.model_dump())
            return ToolResult(text_result_for_llm="Plan submitted successfully.")
        except (ValidationError, Exception) as exc:
            log.warning("create_plan_invalid_args", error=str(exc))
            return ToolResult(
                text_result_for_llm="Invalid plan format. Please try again.",
                result_type="failure",
            )

    return Tool(
        name="create_plan",
        description=(
            "Submit the task decomposition plan. Call this tool with a JSON object "
            "containing 'team_description' (string) and 'tasks' (array of objects "
            "with subject, description, worker_role, worker_name, blocked_by_indices)."
        ),
        handler=_handler,
        parameters=SwarmPlan.model_json_schema(),
        skip_permission=True,
    )


def create_report_tool(report_holder: list[str]) -> Tool:
    """Return a tool the leader calls to submit the synthesis report.

    The report text is captured in *report_holder*.
    """

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        args = invocation.arguments or {}
        try:
            report = SwarmReport.model_validate(args)
            report_holder.append(report.report)
            return ToolResult(text_result_for_llm="Report submitted successfully.")
        except (ValidationError, Exception) as exc:
            log.warning("submit_report_invalid_args", error=str(exc))
            return ToolResult(
                text_result_for_llm="Invalid report format.",
                result_type="failure",
            )

    return Tool(
        name="submit_report",
        description="Submit the final synthesis report. Call with {'report': 'your report text'}.",
        handler=_handler,
        parameters=SwarmReport.model_json_schema(),
        skip_permission=True,
    )
