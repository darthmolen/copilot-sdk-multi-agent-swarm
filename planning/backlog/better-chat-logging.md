# Better Logging for Chat Refinement Sessions

## Context

During the first live test of the refinement chat, the synthesis agent hallucinated "spinning up a research team" but the logs only showed generic `leader.chat_tool_start` / `leader.chat_tool_result` events without tool names. It took manual log analysis to determine nothing was actually happening after the final `leader.chat_message`. We need richer logging for chat sessions.

## What's Missing

1. **Tool names not logged in chat events** — `leader.chat_tool_start` is forwarded but the tool name isn't in the forwarded event log line (only in the event data payload). Need to extract and log `tool_name` at INFO level.

2. **No log for chat request received** — When `POST /api/swarm/{id}/chat` is called, no INFO log records the message or swarm_id. Should log at INFO: `chat_request_received swarm_id=... message_length=...`

3. **No log for chat response complete** — When `leader.chat_message` is emitted from `chat()`, should log at INFO: `chat_response_complete swarm_id=... response_length=... tool_calls=N duration_ms=...`

4. **No log for session resume** — When `client.resume_session()` is called, should log: `synthesis_session_resumed session_id=... swarm_id=...`

5. **No duration tracking** — Chat response time isn't measured. Should track from request to `session.idle`.

## Implementation

Add structlog calls in:
- `rest.py` — log chat request at endpoint entry
- `orchestrator.py` — log session resume, tool calls with names, response complete with duration
- `main.py` WS forwarder — extract tool_name from `leader.chat_tool_start` data for log line
