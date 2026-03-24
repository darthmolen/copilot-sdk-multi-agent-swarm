"""Spike: Test tool compliance WITHOUT custom_agents.

Hypothesis: custom_agents adds the copilot-cli agent framework layer which
overrides tool instructions. Without custom_agents, using only
system_message mode:"replace" + tools, the model might follow
tool instructions better.

Compare with spike_model_tool_compliance.py results.
"""

import asyncio
import json
import shutil
import time
from dataclasses import dataclass, field

MODELS_TO_TEST = [
    "claude-haiku-4.5",
    "claude-sonnet-4.6",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-5.1",
    "gpt-5.2",
    "gemini-3-pro-preview",
]

SYSTEM_PROMPT = """You are a research agent. You have 4 tools available.

You MUST call them in this order:
1. Call task_update with task_id="t1" and status="in_progress"
2. Think about your answer (RAG = Retrieval-Augmented Generation)
3. Call task_update with task_id="t1", status="completed", and result="your 2-sentence answer"
4. Call inbox_send with to="leader" and message="Task t1 complete"

Do NOT respond with text. ONLY use the tools. Call task_update first."""

TASK_PROMPT = "What does RAG mean? Call task_update and inbox_send as instructed. Do not write text, only call tools."


@dataclass
class ModelResult:
    model: str
    called_task_update: int = 0
    called_inbox_send: int = 0
    called_other: list[str] = field(default_factory=list)
    text_response: str = ""
    elapsed_seconds: float = 0
    error: str = ""


async def test_model(model_id: str) -> ModelResult:
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler
    from backend.swarm.tools import create_swarm_tools
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

        tool_events: list[str] = []

        def track(event_data: dict) -> None:
            tool_events.append(event_data.get("event", "?"))

        tools = create_swarm_tools("worker", tb, inbox, event_callback=track)

        client = CopilotClient(SubprocessConfig(cli_path=shutil.which("copilot"), use_stdio=True))
        await client.start()

        # NO custom_agents — just system_message + tools + available_tools
        session = await client.create_session(
            on_permission_request=PermissionHandler.approve_all,
            model=model_id,
            system_message={"mode": "replace", "content": SYSTEM_PROMPT},
            tools=tools,
            available_tools=["task_update", "inbox_send", "inbox_receive", "task_list"],
        )

        messages = []
        sdk_tools = []

        def handler(event):
            et = getattr(getattr(event, "type", ""), "value", "")
            data = getattr(event, "data", None)
            if et == "assistant.message":
                c = getattr(data, "content", None)
                if c:
                    messages.append(c)
            if "tool" in et and "execution" in et:
                tn = getattr(data, "tool_name", None)
                if tn:
                    sdk_tools.append(tn)

        session.on(handler)

        try:
            await session.send_and_wait(TASK_PROMPT, timeout=30)
        except TimeoutError:
            pass

        await asyncio.sleep(2)

        for tc in sdk_tools + tool_events:
            tcl = tc.lower()
            if "task_update" in tcl:
                result.called_task_update += 1
            elif "inbox_send" in tcl:
                result.called_inbox_send += 1
            else:
                result.called_other.append(tc)

        if messages:
            result.text_response = messages[-1][:200]

        tasks = await tb.get_tasks()
        if tasks and tasks[0].result:
            result.text_response = f"[via tool] {tasks[0].result[:200]}"

        await client.stop()

    except Exception as e:
        result.error = str(e)[:200]

    result.elapsed_seconds = round(time.time() - start, 1)
    return result


async def main():
    print(f"Testing {len(MODELS_TO_TEST)} models WITHOUT custom_agents...")
    print(f"Using: system_message mode:'replace' + tools + available_tools")
    print()

    results: list[ModelResult] = []

    for model_id in MODELS_TO_TEST:
        print(f"Testing {model_id}...", end=" ", flush=True)
        r = await test_model(model_id)
        results.append(r)

        score = r.called_task_update + r.called_inbox_send
        status = "✅" if score >= 2 else "⚠️" if score >= 1 else "❌"
        print(f"{status} task_update={r.called_task_update} inbox_send={r.called_inbox_send} "
              f"other={len(r.called_other)} time={r.elapsed_seconds}s"
              f"{' ERROR: ' + r.error if r.error else ''}")

    print(f"\n{'='*80}")
    print(f"{'Model':<30} {'task_update':>11} {'inbox_send':>11} {'other':>6} {'time':>6} {'score':>6}")
    print(f"{'-'*80}")

    results.sort(key=lambda r: r.called_task_update + r.called_inbox_send, reverse=True)

    for r in results:
        score = r.called_task_update + r.called_inbox_send
        emoji = "✅" if score >= 2 else "⚠️" if score >= 1 else "❌"
        print(f"{r.model:<30} {r.called_task_update:>11} {r.called_inbox_send:>11} "
              f"{len(r.called_other):>6} {r.elapsed_seconds:>5.1f}s {emoji:>6}")

    outpath = "planning/spikes/spike_no_custom_agents_results.json"
    with open(outpath, "w") as f:
        json.dump([{"model": r.model, "task_update": r.called_task_update,
                    "inbox_send": r.called_inbox_send, "other": r.called_other,
                    "elapsed": r.elapsed_seconds, "error": r.error,
                    "response": r.text_response} for r in results], f, indent=2)
    print(f"\nResults saved to {outpath}")


if __name__ == "__main__":
    asyncio.run(main())
