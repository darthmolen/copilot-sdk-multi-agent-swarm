"""Swarm tool abstractions and factory for agent-callable tools.

Provides a lightweight Tool protocol compatible with copilot-sdk's define_tool,
and a factory that creates closure-bound tools for task and inbox operations.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.swarm.inbox_system import InboxSystem
from backend.swarm.task_board import TaskBoard


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
