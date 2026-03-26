"""
hybrid_pipeline.py — Orchestrates all three retrieval strategies using four
composition patterns defined by the Architect.

Patterns
--------
1. **Layered**   — Run all three strategies, pool results, build one prompt.
2. **Routed**    — Classify the query and delegate to the most appropriate
                   strategy (or all three for ambiguous queries).
3. **Cascading** — Start with Memory; add Vector only if best score is weak;
                   add RAG only if still weak.  Minimises latency for queries
                   that memory alone can answer confidently.
4. **Temporal**  — Split the token budget across three time-horizon windows
                   (immediate / session / background) and resize them as task
                   progress advances from 0.0 to 1.0.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone
from typing import Optional

from prefill.interfaces import ContextBlock, SystemPromptBuilder
from prefill.memory_strategy import MemoryStrategy, SQLiteMemoryStore
from prefill.rag_strategy import RAGStrategy
from prefill.vector_strategy import VectorStrategy


# ---------------------------------------------------------------------------
# Query router helpers
# ---------------------------------------------------------------------------

# Keywords that steer routing decisions.  Lists are ordered from most specific
# to least specific so an early match wins without complex regex logic.
_MEMORY_KEYWORDS = frozenset([
    "remember", "last time", "my preference", "i prefer", "i like", "i told",
    "last session", "before", "what i said", "you know me",
])
_VECTOR_KEYWORDS = frozenset([
    "rule", "policy", "tool", "capability", "allowed", "forbidden",
    "what can you", "what can i", "how are you configured",
])
_RAG_KEYWORDS = frozenset([
    "how", "what", "explain", "define", "describe", "tell me about",
    "why", "when", "where", "who", "which",
])


def _classify_query(query: str) -> str:
    """
    Return "memory", "vector", "rag", or "all" based on simple keyword matching.

    The classification is intentionally coarse — a single lowercased substring
    scan — because this is a routing heuristic, not a semantic classifier.  For
    production, replace with a fast intent-classification model.
    """
    q_lower = query.lower()

    # Memory keywords take precedence: personalisation context is most valuable.
    for kw in _MEMORY_KEYWORDS:
        if kw in q_lower:
            return "memory"

    # Vector keywords next: policy/tool questions need authoritative rules.
    for kw in _VECTOR_KEYWORDS:
        if kw in q_lower:
            return "vector"

    # RAG keywords are the broadest — many queries start with "how" or "what".
    for kw in _RAG_KEYWORDS:
        if kw in q_lower:
            return "rag"

    # Ambiguous query — use all strategies and let the builder prioritise.
    return "all"


# ---------------------------------------------------------------------------
# HybridPipeline
# ---------------------------------------------------------------------------

class HybridPipeline:
    """
    Orchestrates RAGStrategy, VectorStrategy, and MemoryStrategy using four
    composition patterns.

    All ``run_*`` methods return a fully assembled system prompt string.

    Parameters
    ----------
    rag     : Indexed RAGStrategy instance.
    vector  : Indexed VectorStrategy instance.
    memory  : MemoryStrategy instance wrapping a populated MemoryStore.
    builder : SystemPromptBuilder used to assemble the final prompt.
    """

    def __init__(
        self,
        rag: RAGStrategy,
        vector: VectorStrategy,
        memory: MemoryStrategy,
        builder: SystemPromptBuilder,
    ) -> None:
        self._rag = rag
        self._vector = vector
        self._memory = memory
        self._builder = builder

    # ------------------------------------------------------------------
    # Pattern 1 — Layered
    # ------------------------------------------------------------------

    def run_layered(
        self,
        query: str,
        base_prompt: str,
        token_budget: int,
    ) -> str:
        """
        Run all three strategies and merge their results into one prompt.

        The token budget is split equally across strategies up-front (⅓ each).
        This is a conservative partition that ensures no single strategy can
        crowd out the others.  The SystemPromptBuilder then applies the global
        memory > vector > rag priority over the pooled blocks.

        Parameters
        ----------
        query        : User query to retrieve context for.
        base_prompt  : Static base instruction text.
        token_budget : Total word-count ceiling for the returned prompt.
        """
        # Divide budget equally across three layers.  Integer division is fine;
        # a few tokens of rounding error are negligible.
        per_layer = token_budget // 3

        memory_blocks = self._memory.retrieve(query, top_k=5, token_budget=per_layer)
        vector_blocks = self._vector.retrieve(query, top_k=5, token_budget=per_layer)
        rag_blocks    = self._rag.retrieve(query, top_k=5, token_budget=per_layer)

        all_blocks = memory_blocks + vector_blocks + rag_blocks
        return self._builder.build(base_prompt, all_blocks, token_budget)

    # ------------------------------------------------------------------
    # Pattern 2 — Routed
    # ------------------------------------------------------------------

    def run_routed(
        self,
        query: str,
        base_prompt: str,
        token_budget: int,
    ) -> str:
        """
        Classify the query and route to the most appropriate strategy (or all).

        Routing avoids wasting the token budget on irrelevant context.  A
        memory question doesn't need RAG chunks; a document question doesn't
        need persona blocks.  Routing also speeds up retrieval by skipping
        unused strategies entirely.

        Classification rules (keyword-based)
        -------------------------------------
        - "how / what / explain / define" → RAG
        - "rule / policy / tool / capability" → Vector
        - "remember / last time / my preference / I prefer" → Memory
        - anything else → all three
        """
        route = _classify_query(query)

        if route == "memory":
            blocks = self._memory.retrieve(query, top_k=8, token_budget=token_budget)
        elif route == "vector":
            blocks = self._vector.retrieve(query, top_k=8, token_budget=token_budget)
        elif route == "rag":
            blocks = self._rag.retrieve(query, top_k=8, token_budget=token_budget)
        else:  # "all"
            per = token_budget // 3
            blocks = (
                self._memory.retrieve(query, top_k=5, token_budget=per)
                + self._vector.retrieve(query, top_k=5, token_budget=per)
                + self._rag.retrieve(query, top_k=5, token_budget=per)
            )

        return self._builder.build(base_prompt, blocks, token_budget)

    # ------------------------------------------------------------------
    # Pattern 3 — Cascading
    # ------------------------------------------------------------------

    def run_cascading(
        self,
        query: str,
        base_prompt: str,
        token_budget: int,
        memory_threshold: float = 0.65,
        vector_threshold: float = 0.55,
    ) -> str:
        """
        Cascade through strategies, augmenting only when confidence is low.

        Algorithm
        ---------
        1. Ask Memory for top-5 results.
        2. If the max relevance_score ≥ memory_threshold → done.
        3. Otherwise, also ask Vector and add its blocks.
        4. If the new max ≥ vector_threshold → done.
        5. Otherwise, also ask RAG and add its blocks.

        This minimises total retrieval cost: for personal/preference queries
        that Memory answers confidently, we never hit Vector or RAG.

        Parameters
        ----------
        memory_threshold : Minimum score for Memory alone to satisfy the query.
        vector_threshold : Minimum score after Memory+Vector before RAG is tried.
        """
        all_blocks: list[ContextBlock] = []
        remaining = token_budget

        # Stage 1: Memory
        memory_blocks = self._memory.retrieve(query, top_k=5, token_budget=remaining)
        all_blocks.extend(memory_blocks)
        remaining -= sum(b.token_count for b in memory_blocks)

        max_score = max((b.relevance_score for b in memory_blocks), default=0.0)

        if max_score >= memory_threshold:
            # Memory answered confidently — no need to go deeper.
            return self._builder.build(base_prompt, all_blocks, token_budget)

        # Stage 2: Vector augmentation
        vector_blocks = self._vector.retrieve(query, top_k=5, token_budget=remaining)
        all_blocks.extend(vector_blocks)
        remaining -= sum(b.token_count for b in vector_blocks)

        max_score = max(
            (b.relevance_score for b in all_blocks), default=0.0
        )

        if max_score >= vector_threshold:
            return self._builder.build(base_prompt, all_blocks, token_budget)

        # Stage 3: RAG augmentation (last resort)
        rag_blocks = self._rag.retrieve(query, top_k=5, token_budget=remaining)
        all_blocks.extend(rag_blocks)

        return self._builder.build(base_prompt, all_blocks, token_budget)

    # ------------------------------------------------------------------
    # Pattern 4 — Temporal
    # ------------------------------------------------------------------

    def run_temporal(
        self,
        query: str,
        base_prompt: str,
        token_budget: int,
        task_progress: float = 0.0,
    ) -> str:
        """
        Split the budget across three time-horizon windows that shift with progress.

        Budget fractions
        ----------------
        immediate  (Memory) : 0.25 + 0.20 × task_progress
        session    (Vector) : 0.35 (fixed — behavioural rules are always needed)
        background (RAG)    : remainder = 1 - immediate - session

        As *task_progress* advances from 0.0 → 1.0, the immediate (short-term
        memory) window grows from 25 % to 45 %, squeezing the background (RAG)
        window from 40 % to 20 %.  This reflects the intuition that as a task
        progresses, accumulated in-context history matters more than generic
        background knowledge.

        Parameters
        ----------
        task_progress : Float in [0.0, 1.0].  0.0 = task just started;
                        1.0 = task nearly complete.
        """
        # Clamp progress to valid range to tolerate off-by-epsilon callers.
        progress = max(0.0, min(1.0, task_progress))

        immediate_frac = 0.25 + 0.20 * progress
        session_frac   = 0.35
        # Background gets whatever is left; guaranteed ≥ 0 due to clamping.
        background_frac = max(0.0, 1.0 - immediate_frac - session_frac)

        immediate_budget  = max(1, int(token_budget * immediate_frac))
        session_budget    = max(1, int(token_budget * session_frac))
        background_budget = max(1, int(token_budget * background_frac))

        # Window 1 — Immediate (recent memory, highest relevance to current context)
        memory_blocks = self._memory.retrieve(query, top_k=5, token_budget=immediate_budget)

        # Window 2 — Session (stable behavioural rules for this interaction)
        vector_blocks = self._vector.retrieve(query, top_k=5, token_budget=session_budget)

        # Window 3 — Background (general knowledge, lowest urgency)
        rag_blocks = self._rag.retrieve(query, top_k=5, token_budget=background_budget)

        all_blocks = memory_blocks + vector_blocks + rag_blocks
        return self._builder.build(base_prompt, all_blocks, token_budget)


# ---------------------------------------------------------------------------
# Demo setup helpers
# ---------------------------------------------------------------------------

def _build_rag() -> RAGStrategy:
    """Index a short async/Python document and return a ready RAGStrategy."""
    doc = textwrap.dedent("""\
        Python's asyncio module implements a single-threaded cooperative
        multitasking model using an event loop.  Coroutines are defined with
        async def and paused with await, yielding control back to the loop.

        The async/await syntax was introduced in PEP 492 (Python 3.5).  Using
        await inside a coroutine suspends it without blocking the OS thread,
        allowing other coroutines to run in the meantime.  This is ideal for
        I/O-bound workloads like HTTP requests or database queries.

        asyncio.gather() runs several coroutines concurrently.  Errors inside
        coroutines are surfaced as exceptions after await, so standard
        try/except blocks work unchanged inside async functions.
    """)
    rag = RAGStrategy()
    rag.index([doc])
    return rag


def _build_vector() -> VectorStrategy:
    """Author five context blocks and return a ready VectorStrategy."""
    vs = VectorStrategy()
    vs.index_blocks([
        {
            "content": "RULE: Always verify the user's identity before disclosing account details.",
            "block_type": "rule", "version": "2.1", "priority_weight": 0.95,
        },
        {
            "content": (
                "RULE: When a billing dispute is filed, issue a provisional credit "
                "within 24 hours while the investigation is ongoing."
            ),
            "block_type": "rule", "version": "2.1", "priority_weight": 0.90,
        },
        {
            "content": (
                "TOOL: billing_lookup(account_id) → Returns recent charges, "
                "dispute history, and current balance."
            ),
            "block_type": "tool_description", "version": "1.3", "priority_weight": 0.70,
        },
        {
            "content": (
                "TOOL: create_dispute_ticket(account_id, charge_id, reason) → "
                "Opens a formal billing dispute and returns a ticket_id."
            ),
            "block_type": "tool_description", "version": "1.3", "priority_weight": 0.65,
        },
        {
            "content": (
                "PERSONA: You are Alex, a senior billing specialist.  "
                "Acknowledge the customer's frustration before moving to resolution."
            ),
            "block_type": "persona", "version": "1.0", "priority_weight": 0.50,
        },
    ])
    return vs


def _build_memory() -> MemoryStrategy:
    """Seed a SQLiteMemoryStore with a few episodic memories and return a MemoryStrategy."""
    store = SQLiteMemoryStore(user_id="alice")
    now = datetime.now(timezone.utc)
    store.add_memory(
        "User prefers concise answers and dislikes jargon.",
        timestamp=now - timedelta(days=2),
        tags=["preference", "communication"],
        session_id="s1",
    )
    store.add_memory(
        "User is learning async Python and asked about event loops.",
        timestamp=now - timedelta(days=1),
        tags=["interest", "python"],
        session_id="s2",
    )
    store.add_memory(
        "User has an open billing dispute for charge #CHG-9182.",
        timestamp=now - timedelta(hours=3),
        tags=["billing", "dispute"],
        session_id="s3",
    )
    return MemoryStrategy(store)


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    QUERY = "how does async/await work and what are my current billing issues"
    BASE_PROMPT = "You are a helpful, knowledgeable assistant. Be concise and accurate."
    BUDGET = 600

    rag    = _build_rag()
    vector = _build_vector()
    memory = _build_memory()
    builder = SystemPromptBuilder()

    pipeline = HybridPipeline(rag=rag, vector=vector, memory=memory, builder=builder)

    divider = "=" * 70

    # Pattern 1 — Layered
    print(f"\n{divider}")
    print("PATTERN 1: LAYERED (all three strategies, equal budget split)")
    print(divider)
    print(pipeline.run_layered(QUERY, BASE_PROMPT, BUDGET))

    # Pattern 2 — Routed
    print(f"\n{divider}")
    print(f"PATTERN 2: ROUTED (query classified as: '{_classify_query(QUERY)}')")
    print(divider)
    print(pipeline.run_routed(QUERY, BASE_PROMPT, BUDGET))

    # Pattern 3 — Cascading
    print(f"\n{divider}")
    print("PATTERN 3: CASCADING (memory first, augment if score < threshold)")
    print(divider)
    print(pipeline.run_cascading(QUERY, BASE_PROMPT, BUDGET))

    # Pattern 4 — Temporal (early in task: progress=0.1)
    print(f"\n{divider}")
    print("PATTERN 4: TEMPORAL (task_progress=0.1 — early stage)")
    print(divider)
    print(pipeline.run_temporal(QUERY, BASE_PROMPT, BUDGET, task_progress=0.1))

    # Pattern 4 — Temporal (late in task: progress=0.9)
    print(f"\n{divider}")
    print("PATTERN 4: TEMPORAL (task_progress=0.9 — late stage, memory window grows)")
    print(divider)
    print(pipeline.run_temporal(QUERY, BASE_PROMPT, BUDGET, task_progress=0.9))
