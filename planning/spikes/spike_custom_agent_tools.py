"""Spike: Test custom_agents tools field vs session available_tools.

Test 1: Session available_tools=["grep"], custom_agent tools=None
  → Tell agent to do a web search. Expect: blocked (no web_fetch in available_tools)

Test 2: Session available_tools=["web_fetch"], custom_agent tools=["web_fetch"]
  → Tell agent to do a web search for dad jokes. Expect: works
"""

import asyncio
import shutil

PROMPT = "Search the web for the top 3 dad jokes of 2026. Use web_fetch or web_search to find them."


async def run_spike_1():
    """Session available_tools=["grep"], custom_agent tools=None."""
    print("\n" + "=" * 60)
    print("SPIKE 1: session available_tools=[grep], custom_agent tools=None")
    print("=" * 60)

    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    cli_path = shutil.which("copilot")
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()

    session = await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "researcher",
            "displayName": "Researcher",
            "description": "Web researcher",
            "prompt": "You are a web researcher. Use available tools to search the web.",
            "tools": None,  # No restriction at agent level
            "infer": False,
        }],
        agent="researcher",
        available_tools=["grep"],  # Session restricts to grep only
    )

    events = []
    tool_calls = []
    messages = []

    def handler(event):
        et = getattr(getattr(event, "type", ""), "value", str(getattr(event, "type", "")))
        events.append(et)
        data = getattr(event, "data", None)
        if "tool" in et:
            tn = getattr(data, "tool_name", None)
            if tn:
                tool_calls.append(tn)
                print(f"  TOOL: {et} → {tn}")
        if et == "assistant.message":
            content = getattr(data, "content", None)
            if content:
                messages.append(content)
                print(f"  MSG: {content[:200]}")
        if "permission" in et:
            print(f"  PERM: {et}")

    session.on(handler)
    await session.send(PROMPT)
    await asyncio.sleep(20)

    print(f"\nResults:")
    print(f"  Events: {len(events)}")
    print(f"  Tool calls: {tool_calls}")
    print(f"  Messages: {len(messages)}")
    if messages:
        print(f"  Last message: {messages[-1][:300]}")

    await client.stop()
    return tool_calls, messages


async def run_spike_2():
    """Session available_tools=["web_fetch"], custom_agent tools=["web_fetch"]."""
    print("\n" + "=" * 60)
    print("SPIKE 2: session available_tools=[web_fetch], custom_agent tools=[web_fetch]")
    print("=" * 60)

    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    cli_path = shutil.which("copilot")
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()

    session = await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "researcher",
            "displayName": "Researcher",
            "description": "Web researcher",
            "prompt": "You are a web researcher. Use available tools to search the web.",
            "tools": ["web_fetch"],  # Agent restricted to web_fetch
            "infer": False,
        }],
        agent="researcher",
        available_tools=["web_fetch"],  # Session also allows web_fetch
    )

    events = []
    tool_calls = []
    messages = []

    def handler(event):
        et = getattr(getattr(event, "type", ""), "value", str(getattr(event, "type", "")))
        events.append(et)
        data = getattr(event, "data", None)
        if "tool" in et:
            tn = getattr(data, "tool_name", None)
            if tn:
                tool_calls.append(tn)
                print(f"  TOOL: {et} → {tn}")
        if et == "assistant.message":
            content = getattr(data, "content", None)
            if content:
                messages.append(content)
                print(f"  MSG: {content[:200]}")
        if "permission" in et:
            print(f"  PERM: {et}")

    session.on(handler)
    await session.send(PROMPT)
    await asyncio.sleep(20)

    print(f"\nResults:")
    print(f"  Events: {len(events)}")
    print(f"  Tool calls: {tool_calls}")
    print(f"  Messages: {len(messages)}")
    if messages:
        print(f"  Last message: {messages[-1][:300]}")

    await client.stop()
    return tool_calls, messages


async def main():
    tools1, msgs1 = await run_spike_1()
    tools2, msgs2 = await run_spike_2()

    print("\n" + "=" * 60)
    print("COMPARISON")
    print("=" * 60)
    print(f"Spike 1 (grep only): tools={tools1}")
    print(f"Spike 2 (web_fetch): tools={tools2}")
    print(f"Spike 1 used web_fetch: {'web_fetch' in tools1}")
    print(f"Spike 2 used web_fetch: {'web_fetch' in tools2}")


if __name__ == "__main__":
    asyncio.run(main())
