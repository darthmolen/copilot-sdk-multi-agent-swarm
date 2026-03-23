"""Shared fixtures for integration tests against a real copilot-cli process."""

import pytest
import pytest_asyncio
from pathlib import Path


# Mark every test in this directory as integration by default.
pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(scope="module")
async def copilot_client():
    """Start a real Copilot CLI client backed by a subprocess.

    The client is shared across all tests in a single module to avoid
    paying the subprocess-startup cost per test.  Each test should create
    its own session.
    """
    from copilot import CopilotClient, SubprocessConfig

    client = CopilotClient(SubprocessConfig(use_stdio=True))
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"copilot-cli not available: {exc}")
    yield client
    await client.stop()


@pytest.fixture
def event_bus():
    """A fresh EventBus for each test."""
    from backend.events import EventBus

    return EventBus()


@pytest.fixture
def template_loader():
    """TemplateLoader pointing at the project's templates directory."""
    from backend.swarm.template_loader import TemplateLoader

    return TemplateLoader(Path("src/templates"))


@pytest.fixture
def event_collector(event_bus):
    """Subscribe to an EventBus and accumulate (type, data) tuples."""
    events: list[tuple[str, dict]] = []
    event_bus.subscribe(lambda t, d: events.append((t, d)))
    return events
