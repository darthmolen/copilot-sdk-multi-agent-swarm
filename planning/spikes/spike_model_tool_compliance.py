"""Spike: Test which models follow custom tool instructions best.

For each model, create a session with our 4 swarm tools and a simple task.
Measure: did the model call task_update and inbox_send as instructed?

Score each model on tool compliance to find the best fit for swarm workers.
"""

import asyncio
import json
import shutil
import time
from dataclasses import dataclass, field

# Models to test — curated subset for speed (skip slow/expensive ones)
MODELS_TO_TEST = [
    "gpt-5.2",               # NEW — higher tier
    "claude-sonnet-4.6",     # previous best (1 tool call)
    "gemini-3-pro-preview",  # previous best (1 tool call)
]

SYSTEM_PROMPT = """You are a research agent in a multi-agent swarm.

You have 4 coordination tools. You MUST call them in this order:
1. Call task_update with status="in_progress" and task_id="t1"
2. Write your research result as text
3. Call task_update with status="completed", task_id="t1", and result="your findings here"
4. Call inbox_send with to="leader" and message="Task complete"

These tool calls are MANDATORY. Do them now."""

TASK_PROMPT = "Research what RAG means in 2 sentences. Then call task_update and inbox_send as instructed."


@dataclass
class ModelResult:
    model: str
    called_task_update: int = 0
    called_inbox_send: int = 0
    called_inbox_receive: int = 0
    called_task_list: int = 0
    called_other_tools: list[str] = field(default_factory=list)
    text_response: str = ""
    elapsed_seconds: float = 0
    error: str = ""


async def test_model(model_id: str) -> ModelResult:
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler
    from copilot.generated.rpc import SessionAgentSelectParams
    from backend.swarm.tools import create_swarm_tools, Tool
    from backend.swarm.task_board import TaskBoard
    from backend.swarm.inbox_system import InboxSystem

    result = ModelResult(model=model_id)
    start = time.time()

    try:
        tb = TaskBoard()
        await tb.add_task(id="t1", subject="RAG Research", description="Research RAG",
                          worker_role="researcher", worker_name="worker")
        inbox = InboxSystem()
        inbox.register_agent("worker")
        inbox.register_agent("leader")

        # Track tool calls via callback
        tool_calls: list[str] = []

        def track_callback(event_data: dict) -> None:
            tool_calls.append(event_data.get("event", "unknown"))

        tools = create_swarm_tools("worker", tb, inbox, event_callback=track_callback)

        client = CopilotClient(SubprocessConfig(cli_path=shutil.which("copilot"), use_stdio=True))
        await client.start()

        session = await client.create_session(
            on_permission_request=PermissionHandler.approve_all,
            model=model_id,
            system_message={"mode": "replace", "content": SYSTEM_PROMPT},
            tools=tools,
            custom_agents=[{
                "name": "worker",
                "displayName": "Worker",
                "description": "Research worker",
                "prompt": SYSTEM_PROMPT,
                "tools": ["task_update", "inbox_send", "inbox_receive", "task_list"],
                "infer": False,
            }],
            agent="worker",
            available_tools=["task_update", "inbox_send", "inbox_receive", "task_list"],
        )

        # Select agent for tool enforcement
        try:
            await session.rpc.agent.select(SessionAgentSelectParams(name="worker"))
        except Exception:
            pass

        # Collect events
        messages = []
        sdk_tool_calls = []

        def handler(event):
            et = getattr(getattr(event, "type", ""), "value", "")
            data = getattr(event, "data", None)
            if et == "assistant.message":
                content = getattr(data, "content", None)
                if content:
                    messages.append(content)
            if "tool" in et and "execution" in et:
                tn = getattr(data, "tool_name", None)
                if tn:
                    sdk_tool_calls.append(tn)

        session.on(handler)

        # Send and wait
        try:
            await session.send_and_wait(TASK_PROMPT, timeout=30)
        except TimeoutError:
            pass

        # Give a moment for stragglers
        await asyncio.sleep(2)

        # Score
        for tc in sdk_tool_calls + tool_calls:
            tc_lower = tc.lower()
            if "task_update" in tc_lower:
                result.called_task_update += 1
            elif "inbox_send" in tc_lower:
                result.called_inbox_send += 1
            elif "inbox_receive" in tc_lower:
                result.called_inbox_receive += 1
            elif "task_list" in tc_lower:
                result.called_task_list += 1
            else:
                result.called_other_tools.append(tc)

        if messages:
            result.text_response = messages[-1][:200]

        # Also check TaskBoard state
        tasks = await tb.get_tasks()
        t = tasks[0] if tasks else None
        if t and t.result:
            result.text_response = f"[task_update result] {t.result[:200]}"

        await client.stop()

    except Exception as e:
        result.error = str(e)[:200]

    result.elapsed_seconds = round(time.time() - start, 1)
    return result


async def main():
    print(f"Testing {len(MODELS_TO_TEST)} models for tool compliance...")
    print(f"Prompt: {TASK_PROMPT[:80]}...")
    print()

    results: list[ModelResult] = []

    for model_id in MODELS_TO_TEST:
        print(f"Testing {model_id}...", end=" ", flush=True)
        r = await test_model(model_id)
        results.append(r)

        score = r.called_task_update + r.called_inbox_send
        other = len(r.called_other_tools)
        status = "✅" if score >= 2 else "⚠️" if score >= 1 else "❌"
        print(f"{status} task_update={r.called_task_update} inbox_send={r.called_inbox_send} "
              f"other={other} time={r.elapsed_seconds}s"
              f"{' ERROR: ' + r.error if r.error else ''}")

    # Summary table
    print(f"\n{'='*80}")
    print(f"{'Model':<30} {'task_update':>11} {'inbox_send':>11} {'other':>6} {'time':>6} {'score':>6}")
    print(f"{'-'*80}")

    results.sort(key=lambda r: r.called_task_update + r.called_inbox_send, reverse=True)

    for r in results:
        score = r.called_task_update + r.called_inbox_send
        emoji = "✅" if score >= 2 else "⚠️" if score >= 1 else "❌"
        print(f"{r.model:<30} {r.called_task_update:>11} {r.called_inbox_send:>11} "
              f"{len(r.called_other_tools):>6} {r.elapsed_seconds:>5.1f}s {emoji:>6}")

    # Save results
    out = [{"model": r.model, "task_update": r.called_task_update, "inbox_send": r.called_inbox_send,
            "inbox_receive": r.called_inbox_receive, "task_list": r.called_task_list,
            "other_tools": r.called_other_tools, "elapsed": r.elapsed_seconds,
            "error": r.error, "response": r.text_response} for r in results]

    outpath = "planning/spikes/spike_model_results.json"
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {outpath}")


if __name__ == "__main__":
    asyncio.run(main())
