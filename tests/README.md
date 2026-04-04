# Running Tests

## Backend Unit Tests (309+)

```bash
python -m pytest tests/unit/ -x -q
```

Runs all backend unit tests. No external dependencies required — uses mock clients and in-memory stores.

## Frontend Tests (97+)

```bash
cd src/frontend
npx vitest run
```

Runs all React component and reducer tests via Vitest.

## Integration Tests (24+ — requires Postgres)

Integration tests run against a real Postgres instance. Each test gets its own isolated database with real Alembic migrations applied.

### Setup

```bash
# Start Postgres via Docker Compose
docker compose up -d postgres

# Run integration tests
PYTHONPATH=src python -m pytest tests/integration/ -m db -x -q
```

### What happens under the hood

1. The `db_engine` fixture in `tests/integration/conftest.py` creates a fresh `test_{uuid}` database
2. Runs `alembic upgrade head` against that database (real migrations, real schema)
3. Yields an async SQLAlchemy engine connected to the test database
4. After the test: drops the database
5. A session-scoped cleanup fixture drops any leftover `test_*` databases

### Running specific test files

```bash
# Repository tests only
PYTHONPATH=src python -m pytest tests/integration/test_repository.py -m db -xvs

# SwarmService integration tests
PYTHONPATH=src python -m pytest tests/integration/test_swarm_service.py -m db -xvs

# Event logger tests
PYTHONPATH=src python -m pytest tests/integration/test_event_logger.py -m db -xvs
```

### Skipping integration tests

Integration tests are marked with `@pytest.mark.db`. To skip them:

```bash
python -m pytest tests/ -m "not db" -x -q
```

## All Tests Together

```bash
# Unit + integration (requires Postgres for integration)
docker compose up -d postgres
python -m pytest tests/unit/ -x -q
PYTHONPATH=src python -m pytest tests/integration/ -m db -x -q
cd src/frontend && npx vitest run
```

## Test Isolation Pattern

The per-test database isolation pattern in `tests/integration/conftest.py` is reusable across any project with Postgres. Copy the `conftest.py` and adjust the connection strings for your environment. The pattern:

- Creates an ephemeral database per test
- Runs real Alembic migrations (validates both code AND schema)
- Drops the database on teardown
- Session-scoped cleanup catches stragglers
- No SQLite faking — tests run against real Postgres with JSONB, UUID, and proper constraints
