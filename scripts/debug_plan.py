"""Debug script: test create_plan tool registration with real copilot-cli."""

import asyncio
import shutil
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def main():
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    from backend.swarm.tools import create_plan_tool

    cli_path = shutil.which("copilot")
    if not cli_path:
        print("ERROR: copilot not found")
        return

    print(f"Using CLI: {cli_path}")

    # Create plan tool
    plan_holder: list[dict] = []
    plan_tool = create_plan_tool(plan_holder)

    print(f"Tool: name={plan_tool.name}, skip_permission={plan_tool.skip_permission}")
    print(f"Tool type: {type(plan_tool)}")
    print(f"Tool attrs: {[a for a in dir(plan_tool) if not a.startswith('_')]}")

    # Check what the SDK Tool looks like
    from copilot.tools import Tool as SDKTool
    print(f"\nSDK Tool fields: {[f.name for f in SDKTool.__dataclass_fields__.values()]}")
    print(f"Our Tool fields: {[f.name for f in plan_tool.__dataclass_fields__.values()]}")

    # Try creating a session with our tool
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()
    print("\nClient started")

    try:
        print("Creating session with plan tool...")
        session = await client.create_session(
            on_permission_request=PermissionHandler.approve_all,
            system_message={"mode": "replace", "content": "You are a task planner. When given a goal, call the create_plan tool."},
            tools=[plan_tool],
        )
        print(f"Session created: {session.session_id}")

        # Subscribe to events
        events = []
        def on_event(event):
            events.append(event)
            logger.info(f"EVENT: {event.type}")

        session.on(on_event)

        print("Sending goal...")
        msg_id = await session.send("Plan a simple hello world Python script with 2 tasks")
        print(f"Message sent: {msg_id}")

        # Wait for completion
        print("Waiting for events (30s timeout)...")
        await asyncio.sleep(30)

        print(f"\nReceived {len(events)} events")
        for e in events:
            print(f"  {e.type}: {str(e.data)[:200]}")

        print(f"\nPlan holder: {plan_holder}")

    finally:
        await client.stop()
        print("Client stopped")


if __name__ == "__main__":
    asyncio.run(main())
