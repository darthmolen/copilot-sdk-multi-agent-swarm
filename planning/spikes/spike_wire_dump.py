"""Spike: Dump the actual JSON-RPC payload sent by the Python SDK.

Monkey-patches the JSON-RPC transport to capture the session.create payload.
Compare with the Node.js payload to find the divergence in customAgents[n].tools.
"""

import asyncio
import json
import shutil
from unittest.mock import patch


async def main():
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    cli_path = shutil.which("copilot")
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()

    # Monkey-patch to capture outgoing JSON-RPC messages
    captured_payloads: list[dict] = []
    original_send = client._client._send_message

    async def _capturing_send(message):
        try:
            parsed = json.loads(message) if isinstance(message, str) else message
            if isinstance(parsed, dict) and parsed.get("method") == "session.create":
                captured_payloads.append(parsed)
                print(f"\n{'='*60}")
                print("CAPTURED session.create PAYLOAD")
                print(f"{'='*60}")
                print(json.dumps(parsed, indent=2, default=str)[:5000])
        except Exception:
            pass
        return await original_send(message)

    client._client._send_message = _capturing_send

    # Create session with agent.tools=["grep"] — the config that should restrict
    print("Creating session with agent.tools=['grep']...")
    session = await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "researcher",
            "display_name": "Researcher",
            "description": "Web researcher",
            "prompt": "You are a researcher.",
            "tools": ["grep"],
            "infer": False,
        }],
        agent="researcher",
        available_tools=["grep", "web_fetch"],
    )

    print(f"\nSession created: {session.session_id}")

    # Extract just the customAgents portion
    if captured_payloads:
        params = captured_payloads[0].get("params", {})
        ca = params.get("customAgents", [])
        at = params.get("availableTools", None)
        print(f"\n{'='*60}")
        print("KEY FIELDS IN PAYLOAD")
        print(f"{'='*60}")
        print(f"customAgents: {json.dumps(ca, indent=2)}")
        print(f"availableTools: {json.dumps(at)}")
        print(f"agent: {params.get('agent')}")

        # Check if tools field is present in customAgents
        if ca:
            agent_tools = ca[0].get("tools", "MISSING")
            print(f"\ncustomAgents[0].tools = {agent_tools}")
            if agent_tools == "MISSING":
                print("*** BUG: 'tools' field is MISSING from the wire format! ***")
            elif agent_tools is None:
                print("*** tools is None — means 'no restriction' ***")
            elif isinstance(agent_tools, list):
                print(f"*** tools is a list: {agent_tools} — should restrict ***")
    else:
        print("\n*** No session.create payload captured! ***")

    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
