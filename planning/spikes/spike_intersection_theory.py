"""Spike: Test the intersection theory — effective tools = availableTools ∩ agent.tools

The vscode extension claims a tool must be in BOTH availableTools AND customAgents[n].tools
to be callable. The research sub-agent claims availableTools only filters built-ins.

Three tests to settle this:

Test 1: availableTools=["grep","web_fetch"], agent.tools=None
  → Agent should get grep + web_fetch (None = inherit session)
  → Ask agent to list its tools

Test 2: availableTools=["grep","web_fetch"], agent.tools=["grep"]
  → If intersection: agent gets ONLY grep (web_fetch not in agent.tools)
  → If separate: agent gets grep (from agent.tools) + web_fetch (from session?)
  → Ask agent to list its tools

Test 3: availableTools=None (no restriction), agent.tools=["grep","view"]
  → If intersection: agent gets grep + view only (agent restricts)
  → If separate: agent gets grep + view (agent restricts) + all built-ins?
  → Ask agent to web_fetch — should FAIL if agent.tools restricts
"""

import asyncio
import shutil

PROMPT = "List ALL tools you have access to. Be exhaustive — name every single tool."


async def run_test(label: str, available_tools, agent_tools):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"  session available_tools = {available_tools}")
    print(f"  custom_agent tools      = {agent_tools}")
    print(f"{'='*60}")

    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    cli_path = shutil.which("copilot")
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()

    create_kwargs = dict(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "tester",
            "displayName": "Tool Tester",
            "description": "Lists available tools",
            "prompt": "You are a tool testing agent. When asked, list ALL tools available to you.",
            "tools": agent_tools,
            "infer": False,
        }],
        agent="tester",
    )
    if available_tools is not None:
        create_kwargs["available_tools"] = available_tools

    session = await client.create_session(**create_kwargs)

    tool_calls = []
    messages = []

    def handler(event):
        et = getattr(getattr(event, "type", ""), "value", str(getattr(event, "type", "")))
        data = getattr(event, "data", None)
        if "tool" in et and "execution" in et:
            tn = getattr(data, "tool_name", None)
            if tn:
                tool_calls.append(tn)
        if et == "assistant.message":
            content = getattr(data, "content", None)
            if content:
                messages.append(content)
        if et == "session.tools_updated":
            # This event tells us what tools are actually available
            tools_list = getattr(data, "tools", None)
            if tools_list:
                print(f"  TOOLS_UPDATED: {[getattr(t, 'name', t) for t in tools_list]}")

    session.on(handler)
    await session.send(PROMPT)
    await asyncio.sleep(15)

    print(f"\nResults:")
    print(f"  Tool calls made: {tool_calls}")
    if messages:
        print(f"  Agent response: {messages[-1][:500]}")
    else:
        print(f"  Agent response: (none)")

    await client.stop()
    return tool_calls, messages


async def main():
    # Test 1: availableTools restricts session, agent inherits
    await run_test(
        "availableTools=[grep,web_fetch], agent.tools=None",
        available_tools=["grep", "web_fetch"],
        agent_tools=None,
    )

    # Test 2: INTERSECTION test — does agent.tools further restrict?
    await run_test(
        "availableTools=[grep,web_fetch], agent.tools=[grep]",
        available_tools=["grep", "web_fetch"],
        agent_tools=["grep"],
    )

    # Test 3: No session restriction, agent restricts
    await run_test(
        "availableTools=None, agent.tools=[grep,view]",
        available_tools=None,
        agent_tools=["grep", "view"],
    )


if __name__ == "__main__":
    asyncio.run(main())
