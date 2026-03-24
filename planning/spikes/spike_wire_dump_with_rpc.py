"""Spike: Verify agent selection state after session creation.

The wire payload is correct. Check if rpc.agent.getCurrent shows the right agent
and if the agent's tools list matches what we sent.
"""

import asyncio
import shutil


async def main():
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    cli_path = shutil.which("copilot")
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()

    session = await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "researcher",
            "display_name": "Researcher",
            "description": "Web researcher",
            "prompt": "You are a researcher. Only use grep.",
            "tools": ["grep"],
            "infer": False,
        }],
        agent="researcher",
        available_tools=["grep", "web_fetch"],
    )

    print(f"Session: {session.session_id}")

    # Check agent state via RPC
    try:
        agent_list = await session.rpc.agent.list()
        print(f"\nagent.list(): {agent_list}")
    except Exception as e:
        print(f"agent.list() error: {e}")

    try:
        current = await session.rpc.agent.get_current()
        print(f"agent.getCurrent(): {current}")
    except Exception as e:
        print(f"agent.getCurrent() error: {e}")

    # Now ask the agent what tools it has
    events = []
    messages = []

    def handler(event):
        et = getattr(getattr(event, "type", ""), "value", "")
        data = getattr(event, "data", None)
        if et == "assistant.message":
            content = getattr(data, "content", None)
            tool_reqs = getattr(data, "tool_requests", None)
            if content:
                messages.append(content)
        if et == "session.tools_updated":
            tools = getattr(data, "tools", None)
            if tools:
                print(f"\nsession.tools_updated: {[getattr(t, 'name', str(t)) for t in tools[:20]]}")

    session.on(handler)
    await session.send("What tools do you have? List every tool name.")
    await asyncio.sleep(15)

    if messages:
        print(f"\nAgent response:\n{messages[-1][:600]}")

    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
