"""
interfaces.py — Shared abstractions for the system-prompt pre-fill framework.

All concrete strategies (RAG, Vector, Memory) depend only on the types
defined here, making it straightforward to swap or mock any layer in tests.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ContextBlock:
    """
    A single piece of retrieved context that may be injected into a system prompt.

    Attributes
    ----------
    id            : Stable identifier (e.g. chunk hash, memory UUID).
    content       : Plain-text content to inject.
    source        : Which retrieval layer produced this block.
    relevance_score: 0.0–1.0 score used for prioritisation and budget gating.
    token_count   : Word-count approximation of *content* (no tokeniser needed).
    metadata      : Source-specific key/value pairs (see required keys below).

    Required metadata keys by source
    ---------------------------------
    "rag"    → {"source_uri": str, "chunk_index": int, "parent_doc_id": str}
    "vector" → {"block_type": str, "version": str, "priority_weight": float}
    "memory" → {"memory_type": "episodic"|"semantic", "user_id": str, "timestamp": str}
    """
    id: str
    content: str
    source: Literal["rag", "vector", "memory"]
    relevance_score: float
    token_count: int
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class PromptBudgetExceededError(Exception):
    """
    Raised when the *base_prompt* alone already exceeds the caller's token budget.

    We raise rather than silently truncate so the caller knows it must either
    shorten the base prompt or increase the budget ceiling.
    """


# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------

class RetrievalStrategy(ABC):
    """
    Common interface for all retrieval back-ends.

    Implementors must handle the full index→retrieve lifecycle so that the
    HybridPipeline can treat every strategy identically.
    """

    @abstractmethod
    def retrieve(self, query: str, top_k: int, token_budget: int) -> list[ContextBlock]:
        """
        Return up to *top_k* blocks whose cumulative token_count ≤ token_budget.

        Blocks must be ordered by descending relevance_score.
        """

    @abstractmethod
    def index(self, documents: list[str]) -> None:
        """
        Ingest *documents* into the strategy's internal store.

        May be called multiple times; successive calls should *add* to (not
        replace) the existing index unless the implementation documents otherwise.
        """


class MemoryStore(ABC):
    """
    Persistent (or in-memory) store for episodic and semantic memories.

    A concrete implementation (e.g. SQLiteMemoryStore) backs this with a real
    DB, while a mock can keep everything in a plain list for tests.
    """

    @abstractmethod
    def add_memory(self, content: str, timestamp: datetime, tags: list[str]) -> str:
        """
        Persist a new memory and return its unique memory_id (uuid4 string).
        """

    @abstractmethod
    def retrieve_memories(self, query: str, top_k: int) -> list[ContextBlock]:
        """
        Return up to *top_k* non-archived memories ranked by a
        combined similarity + recency score.
        """

    @abstractmethod
    def consolidate(self) -> None:
        """
        Collapse episodic memories into semantic summaries and archive the originals.

        Consolidation reduces long-term storage growth and surfaces durable facts
        (preferences, recurring patterns) that are more useful than raw episodes.
        """


# ---------------------------------------------------------------------------
# SystemPromptBuilder
# ---------------------------------------------------------------------------

# Section header labels keyed by source name.
_SECTION_HEADERS: dict[str, str] = {
    "memory": "[MEMORY CONTEXT]",
    "vector": "[BEHAVIORAL CONTEXT]",
    "rag":    "[KNOWLEDGE CONTEXT]",
}


class SystemPromptBuilder:
    """
    Assembles a final system prompt from a base prompt and a pool of ContextBlocks.

    Priority order (highest → lowest): memory > vector > rag.

    Within each source tier blocks are sorted by relevance_score descending so
    the most relevant content is always included first when the budget is tight.
    Blocks that don't fit are silently omitted — we never truncate mid-block
    because a partial context block is often worse than no context at all.
    """

    # Canonical priority order used for sorting and section placement.
    SOURCE_PRIORITY: list[str] = ["memory", "vector", "rag"]

    def build(
        self,
        base_prompt: str,
        blocks: list[ContextBlock],
        token_budget: int,
    ) -> str:
        """
        Build and return the final system prompt string.

        Parameters
        ----------
        base_prompt  : The static instruction text provided by the caller.
        blocks       : Pool of candidate ContextBlocks from any/all sources.
        token_budget : Hard ceiling on total word-count of the result.

        Returns
        -------
        Assembled prompt string with section headers separating each source tier.

        Raises
        ------
        PromptBudgetExceededError
            If *base_prompt* alone exceeds *token_budget*.
        """
        # Word-count approximation: splitting on whitespace is fast and
        # consistent with how token_count is set on ContextBlock objects,
        # so the arithmetic stays coherent throughout the pipeline.
        base_tokens = len(base_prompt.split())

        if base_tokens > token_budget:
            raise PromptBudgetExceededError(
                f"Base prompt uses {base_tokens} tokens but budget is only {token_budget}."
            )

        remaining = token_budget - base_tokens

        # Group blocks by source so we can apply priority ordering tier-by-tier.
        # A dict-of-lists also makes it easy to sort within each tier.
        by_source: dict[str, list[ContextBlock]] = {s: [] for s in self.SOURCE_PRIORITY}
        for block in blocks:
            if block.source in by_source:
                by_source[block.source].append(block)

        # Sort each tier by relevance_score descending so greedy filling picks
        # the highest-value blocks first within the budget for that tier.
        for source in self.SOURCE_PRIORITY:
            by_source[source].sort(key=lambda b: b.relevance_score, reverse=True)

        # Greedy fill: iterate sources in priority order, accumulate sections.
        sections: list[str] = []

        for source in self.SOURCE_PRIORITY:
            tier_blocks = by_source[source]
            if not tier_blocks:
                continue

            chosen: list[str] = []
            for block in tier_blocks:
                # +1 for the blank-line separator we'll add between blocks.
                if block.token_count <= remaining:
                    chosen.append(block.content)
                    remaining -= block.token_count
                # We omit, never truncate — a partial block misleads the model.

            if chosen:
                header = _SECTION_HEADERS[source]
                # Join chosen blocks with a blank line for visual separation;
                # this also makes multi-block sections easier to parse in tests.
                body = "\n\n".join(chosen)
                sections.append(f"{header}\n{body}")

        if not sections:
            # All blocks were too large or the pool was empty — return bare base prompt.
            return base_prompt

        # Place retrieved context *above* the base prompt so the model reads
        # the grounding information before its instructions, matching common
        # practices for RAG-augmented system prompts.
        context_str = "\n\n".join(sections)
        return f"{context_str}\n\n{base_prompt}"


# ---------------------------------------------------------------------------
# Quick demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import datetime as _dt

    # Build a small set of mock blocks across all three source types.
    mock_blocks = [
        ContextBlock(
            id="mem-1",
            content="User prefers concise answers and dislikes jargon.",
            source="memory",
            relevance_score=0.92,
            token_count=9,
            metadata={
                "memory_type": "semantic",
                "user_id": "user-42",
                "timestamp": _dt.utcnow().isoformat(),
            },
        ),
        ContextBlock(
            id="vec-1",
            content="Always respond in the user's language. Never switch languages mid-reply.",
            source="vector",
            relevance_score=0.85,
            token_count=13,
            metadata={
                "block_type": "rule",
                "version": "1.0",
                "priority_weight": 0.9,
            },
        ),
        ContextBlock(
            id="rag-1",
            content="Python's asyncio library provides a single-threaded concurrency model.",
            source="rag",
            relevance_score=0.78,
            token_count=12,
            metadata={
                "source_uri": "docs/asyncio.md",
                "chunk_index": 0,
                "parent_doc_id": "asyncio-doc",
            },
        ),
        # This block is too large to fit within the demo budget — it should be omitted.
        ContextBlock(
            id="rag-2",
            content=" ".join(["word"] * 200),  # 200 tokens — intentionally oversized
            source="rag",
            relevance_score=0.95,
            token_count=200,
            metadata={
                "source_uri": "docs/big.md",
                "chunk_index": 0,
                "parent_doc_id": "big-doc",
            },
        ),
    ]

    builder = SystemPromptBuilder()
    base = "You are a helpful assistant."
    budget = 100  # tight budget so the oversized rag-2 block is dropped

    result = builder.build(base, mock_blocks, budget)
    print("=== SystemPromptBuilder demo ===\n")
    print(result)
    print(f"\n[Token budget: {budget}, base tokens: {len(base.split())}]")
