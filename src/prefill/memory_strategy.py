"""
memory_strategy.py — Episodic and semantic memory backed by SQLite (:memory:).

Two classes are provided:

* ``SQLiteMemoryStore`` — implements ``MemoryStore`` with an in-process SQLite
  DB so tests run entirely without disk I/O.
* ``MemoryStrategy`` — implements ``RetrievalStrategy`` by wrapping any
  ``MemoryStore``.

Recency decay
-------------
Cosine similarity alone would surface old memories that happen to share
vocabulary with the query.  We apply an exponential decay:

    score = cosine_similarity × exp(-0.05 × days_since_creation)

λ = 0.05 means a memory that is 14 days old retains ~50 % of its raw score,
while one that is 1 day old retains ~95 %.  This is a simple but effective
prior that recent events are more relevant than distant ones.

Consolidation
-------------
After enough episodic memories accumulate, ``consolidate()`` groups them by
user, concatenates their content with a "Summary: " prefix, stores the result
as a semantic memory, and archives the originals.  In production you would
replace the concatenation with an LLM summarisation call; the interface stays
the same.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from prefill.interfaces import ContextBlock, MemoryStore, RetrievalStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_embedding(text: str, dim: int = 128) -> np.ndarray:
    """
    Deterministic unit-normalised mock embedding seeded from SHA-256 of text.

    See rag_strategy.py for a full rationale; this is the same function
    duplicated here to keep each module self-contained without a shared utils
    module (which would add an import dependency chain that complicates testing).
    """
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16) % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm == 0.0:
        return vec
    return vec / norm


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Dot product of two pre-normalised vectors equals cosine similarity."""
    return float(np.dot(a, b))


def _days_since(timestamp_iso: str) -> float:
    """
    Return fractional days elapsed since *timestamp_iso* (UTC ISO-8601 string).

    We clamp to ≥ 0 so a future timestamp (e.g. from clock skew) doesn't
    produce negative decay and artificially inflate a memory's score.
    """
    try:
        ts = datetime.fromisoformat(timestamp_iso)
        if ts.tzinfo is None:
            # Treat naive timestamps as UTC for consistency.
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return max(0.0, delta.total_seconds() / 86_400.0)
    except (ValueError, OverflowError):
        # Malformed timestamp — treat as very old to be conservative.
        return 9999.0


# ---------------------------------------------------------------------------
# SQLiteMemoryStore
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL,          -- 'episodic' or 'semantic'
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL DEFAULT '',
    timestamp   TEXT NOT NULL,          -- UTC ISO-8601
    tags        TEXT NOT NULL DEFAULT '', -- comma-separated
    archived    INTEGER NOT NULL DEFAULT 0
);
"""


class SQLiteMemoryStore(MemoryStore):
    """
    In-process SQLite-backed ``MemoryStore``.

    Using ``":memory:"`` means the DB lives entirely in RAM — no files are
    created, and the store is isolated between test runs.  For production,
    pass a file path (e.g. ``"memories.db"``) to persist across restarts.

    Parameters
    ----------
    db_path   : SQLite connection string.  Defaults to ``":memory:"``.
    user_id   : Default user identifier stamped on memories when not supplied
                via ``add_memory``.
    session_id: Current conversation session identifier.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        user_id: str = "default-user",
        session_id: str = "",
    ) -> None:
        self._user_id = user_id
        self._session_id = session_id
        # check_same_thread=False is safe here because we never share this
        # connection across OS threads — it's created and used in one process.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # MemoryStore interface
    # ------------------------------------------------------------------

    def add_memory(
        self,
        content: str,
        timestamp: datetime,
        tags: list[str],
        memory_type: str = "episodic",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Insert a new memory record and return its UUID.

        Parameters
        ----------
        content     : Free-text memory content.
        timestamp   : When this memory was formed (caller supplies for testability).
        tags        : Arbitrary labels (e.g. ["preference", "food"]).
        memory_type : "episodic" (raw event) or "semantic" (distilled fact).
        user_id     : Override the store's default user_id for this memory.
        session_id  : Override the store's default session_id.
        """
        memory_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO memories (id, content, memory_type, user_id, session_id,
                                  timestamp, tags, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                memory_id,
                content,
                memory_type,
                user_id or self._user_id,
                session_id or self._session_id,
                timestamp.isoformat(),
                ",".join(tags),
                # archived=0: freshly created memories are always active
            ),
        )
        self._conn.commit()
        return memory_id

    def retrieve_memories(self, query: str, top_k: int) -> list[ContextBlock]:
        """
        Return up to *top_k* non-archived memories ranked by recency-decayed score.

        Score formula
        -------------
        ``score = cosine_similarity(query, memory) × exp(-0.05 × days_since)``

        The exponential decay with λ=0.05 keeps recent memories prominent
        without completely discarding older ones; a two-week-old memory at 0.5
        decay still surfaces if its cosine similarity is high enough.
        """
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE archived = 0"
        ).fetchall()

        if not rows:
            return []

        if not query.strip():
            return []

        query_vec = _mock_embedding(query)

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            sim = _cosine_similarity(query_vec, _mock_embedding(row["content"]))
            decay = math.exp(-0.05 * _days_since(row["timestamp"]))
            # Multiply rather than add so that either very-low similarity
            # OR very-old memories are naturally suppressed.
            combined = sim * decay
            scored.append((combined, row))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[ContextBlock] = []
        for score, row in scored[:top_k]:
            content = row["content"]
            results.append(
                ContextBlock(
                    id=row["id"],
                    content=content,
                    source="memory",
                    relevance_score=round(score, 4),
                    token_count=len(content.split()),
                    metadata={
                        "memory_type": row["memory_type"],
                        "user_id": row["user_id"],
                        "timestamp": row["timestamp"],
                    },
                )
            )
        return results

    def consolidate(self) -> None:
        """
        Summarise episodic memories by user and archive the originals.

        For each user that has at least one non-archived episodic memory we:
        1. Concatenate their episodic memories into a single "Summary: ..." string.
        2. Insert that string as a new *semantic* memory.
        3. Mark the source episodic memories as archived so they are excluded
           from future retrieval (but preserved for audit purposes).

        In production, step 1 would be replaced with an async LLM call that
        produces a coherent prose summary.  The interface is designed to make
        that swap transparent to callers.
        """
        # Fetch all non-archived episodic memories grouped by user.
        rows = self._conn.execute(
            """
            SELECT user_id, id, content, timestamp
            FROM memories
            WHERE archived = 0 AND memory_type = 'episodic'
            ORDER BY user_id, timestamp
            """
        ).fetchall()

        if not rows:
            # Nothing to consolidate — exit early.
            return

        # Group by user_id using a plain dict so we avoid an ORDER BY + GROUP BY
        # dance — we need the individual row ids to archive them later.
        by_user: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_user.setdefault(row["user_id"], []).append(row)

        now_iso = datetime.now(timezone.utc).isoformat()

        for user_id, user_rows in by_user.items():
            # Concatenate is the simplest possible "summarisation".
            # Each episode is prefixed with its timestamp so temporal order
            # is preserved in the semantic memory.
            episode_texts = [
                f"[{r['timestamp'][:10]}] {r['content']}" for r in user_rows
            ]
            summary_content = "Summary: " + " | ".join(episode_texts)

            # Insert the new semantic memory.
            semantic_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO memories (id, content, memory_type, user_id, session_id,
                                      timestamp, tags, archived)
                VALUES (?, ?, 'semantic', ?, '', ?, 'consolidated', 0)
                """,
                (semantic_id, summary_content, user_id, now_iso),
            )

            # Archive the originals so they no longer pollute retrieval results.
            archived_ids = [r["id"] for r in user_rows]
            placeholders = ",".join("?" * len(archived_ids))
            self._conn.execute(
                f"UPDATE memories SET archived = 1 WHERE id IN ({placeholders})",
                archived_ids,
            )

        self._conn.commit()


# ---------------------------------------------------------------------------
# MemoryStrategy
# ---------------------------------------------------------------------------

class MemoryStrategy(RetrievalStrategy):
    """
    ``RetrievalStrategy`` adapter that delegates to a ``MemoryStore`` instance.

    Separating the strategy (how to score and select) from the store (where
    data lives) follows the adapter pattern — you can swap in a Redis-backed
    store, a cloud vector DB, or a mock without changing this class.
    """

    def __init__(self, store: MemoryStore) -> None:
        """
        Parameters
        ----------
        store : Any ``MemoryStore`` implementation.
        """
        self._store = store

    @property
    def store(self) -> MemoryStore:
        """Expose the underlying store so callers can add memories directly."""
        return self._store

    # ------------------------------------------------------------------
    # RetrievalStrategy interface
    # ------------------------------------------------------------------

    def index(self, documents: list[str]) -> None:
        """
        No-op for in-memory mock embeddings.

        In a production system backed by a persistent vector index, this method
        would re-embed all non-archived memories and refresh their stored vectors.
        For the mock embedding approach used here, the embedding is computed
        on-the-fly during retrieval, so there is nothing to pre-compute.
        """
        # Intentional no-op: mock embeddings are computed at retrieve time.

    def retrieve(
        self,
        query: str,
        top_k: int,
        token_budget: int,
    ) -> list[ContextBlock]:
        """
        Retrieve memories from the store and enforce the token budget.

        We request *top_k* blocks from the store, then clip to *token_budget*
        using the same greedy omit-not-truncate rule as all other strategies.

        Parameters
        ----------
        query        : Natural-language query string.
        top_k        : Maximum number of memories to return.
        token_budget : Hard ceiling on total token_count returned.
        """
        blocks = self._store.retrieve_memories(query, top_k)

        # Apply token budget filter — the store's retrieve_memories doesn't
        # know about the pipeline's budget ceiling, so we enforce it here.
        results: list[ContextBlock] = []
        remaining = token_budget
        for block in blocks:
            if block.token_count <= remaining:
                results.append(block)
                remaining -= block.token_count
        return results


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import timedelta

    from prefill.interfaces import SystemPromptBuilder

    print("=== MemoryStrategy demo ===\n")

    store = SQLiteMemoryStore(user_id="alice")
    strategy = MemoryStrategy(store)

    now = datetime.now(timezone.utc)

    # --- Session 1 (3 days ago) ---
    store.add_memory(
        "User said they prefer dark mode in all applications.",
        timestamp=now - timedelta(days=3),
        tags=["preference", "ui"],
        session_id="session-1",
    )
    store.add_memory(
        "User mentioned they are vegetarian and avoid all meat products.",
        timestamp=now - timedelta(days=3, hours=1),
        tags=["preference", "food"],
        session_id="session-1",
    )

    # --- Session 2 (1 day ago) ---
    store.add_memory(
        "User asked about Python asyncio three times — likely learning async programming.",
        timestamp=now - timedelta(days=1),
        tags=["interest", "python"],
        session_id="session-2",
    )

    # --- Session 3 (today) ---
    store.add_memory(
        "User expressed frustration with the slow checkout process.",
        timestamp=now - timedelta(hours=2),
        tags=["sentiment", "checkout"],
        session_id="session-3",
    )

    print(f"Added 4 episodic memories for user 'alice'.\n")

    # Retrieve before consolidation to see raw episodic memories.
    pre_blocks = strategy.retrieve(
        query="what does the user prefer",
        top_k=5,
        token_budget=400,
    )
    print(f"Before consolidation — retrieved {len(pre_blocks)} block(s):")
    for b in pre_blocks:
        print(f"  score={b.relevance_score:.4f}  [{b.metadata['memory_type']:9s}]  {b.content[:70]}...")
    print()

    # Consolidate: episodic memories → semantic summary.
    store.consolidate()
    print("Consolidation complete. Episodic memories archived.\n")

    # Retrieve after consolidation — only the semantic summary should appear.
    post_blocks = strategy.retrieve(
        query="what does the user prefer",
        top_k=5,
        token_budget=400,
    )
    print(f"After consolidation — retrieved {len(post_blocks)} block(s):")
    for b in post_blocks:
        print(f"  score={b.relevance_score:.4f}  [{b.metadata['memory_type']:9s}]  {b.content[:80]}...")
    print()

    builder = SystemPromptBuilder()
    prompt = builder.build(
        base_prompt="You are a personalised assistant. Use user context to tailor your responses.",
        blocks=post_blocks,
        token_budget=600,
    )
    print("--- Assembled memory system prompt ---")
    print(prompt)
