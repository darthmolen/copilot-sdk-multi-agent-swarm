"""
rag_strategy.py — Retrieval-Augmented Generation (RAG) strategy.

Documents are chunked, mock-embedded, and scored by cosine similarity at
query time.  No external embedding API is needed; reproducible vectors are
generated from seeded numpy random generators so tests are deterministic.
"""
from __future__ import annotations

import hashlib
import textwrap
import uuid
from dataclasses import dataclass

import numpy as np

from prefill.interfaces import ContextBlock, RetrievalStrategy

# ---------------------------------------------------------------------------
# Internal chunk representation
# ---------------------------------------------------------------------------

@dataclass
class _Chunk:
    """Holds one text chunk together with its pre-computed embedding vector."""
    chunk_id: str
    text: str
    embedding: np.ndarray
    parent_doc_id: str
    chunk_index: int
    source_uri: str
    token_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_embedding(text: str, dim: int = 128) -> np.ndarray:
    """
    Return a unit-normalised *dim*-dimensional mock embedding for *text*.

    We seed numpy's random generator with a stable hash of the text so the
    same string always produces the same vector.  This matters for two reasons:
      1. Tests remain deterministic across runs without a real embedding model.
      2. Incremental re-indexing of unchanged documents is idempotent.
    """
    # Use the first 8 bytes of SHA-256 as a 64-bit seed so we avoid Python
    # hash randomisation (PYTHONHASHSEED) affecting results across processes.
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16) % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim).astype(np.float32)
    # L2-normalise so cosine similarity reduces to a dot product — cheaper at
    # query time and numerically more stable for high-dimensional vectors.
    norm = np.linalg.norm(vec)
    if norm == 0.0:
        # Degenerate case: return a zero vector rather than dividing by zero.
        return vec
    return vec / norm


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two unit-normalised vectors.

    Because both vectors are already L2-normalised their dot product *is*
    the cosine similarity, so we avoid the expensive norm computation at
    query time (it was paid once during indexing and embedding generation).
    """
    return float(np.dot(a, b))


def _chunk_document(
    text: str,
    doc_id: str,
    source_uri: str,
    chunk_size: int = 100,
    overlap: int = 20,
) -> list[_Chunk]:
    """
    Split *text* into overlapping word-window chunks and embed each one.

    Parameters
    ----------
    text        : Full document text.
    doc_id      : Stable parent document identifier (for metadata).
    source_uri  : Human-readable reference (e.g. file path or URL).
    chunk_size  : Target number of words per chunk (~100 keeps context tight).
    overlap     : Number of words shared between consecutive chunks.  Overlap
                  prevents key sentences from being split across chunk boundaries
                  and improves retrieval recall for multi-sentence queries.
    """
    words = text.split()
    chunks: list[_Chunk] = []

    # Slide a window of *chunk_size* words, advancing by (chunk_size - overlap)
    # each step so the tail of one chunk becomes the head of the next.
    step = max(1, chunk_size - overlap)
    for i, start in enumerate(range(0, len(words), step)):
        chunk_words = words[start : start + chunk_size]
        if not chunk_words:
            break
        chunk_text = " ".join(chunk_words)
        chunks.append(
            _Chunk(
                chunk_id=str(uuid.uuid4()),
                text=chunk_text,
                embedding=_mock_embedding(chunk_text),
                parent_doc_id=doc_id,
                chunk_index=i,
                source_uri=source_uri,
                token_count=len(chunk_words),
            )
        )
    return chunks


# ---------------------------------------------------------------------------
# RAGStrategy
# ---------------------------------------------------------------------------

class RAGStrategy(RetrievalStrategy):
    """
    In-memory RAG strategy using mock numpy embeddings and cosine similarity.

    Typical usage
    -------------
    ::

        rag = RAGStrategy()
        rag.index(["Long document text ...", "Another document ..."])
        blocks = rag.retrieve("how does async/await work", top_k=3, token_budget=512)
    """

    def __init__(self, embedding_dim: int = 128) -> None:
        """
        Parameters
        ----------
        embedding_dim : Dimensionality of mock embedding vectors.  128 is
                        sufficient to give meaningful cosine-similarity rankings
                        while keeping memory usage and compute time tiny.
        """
        self._dim = embedding_dim
        # A flat list of all indexed chunks.  For production you'd swap this
        # for a vector DB (Pinecone, Weaviate, etc.) but the interface stays
        # identical — only _index_store and the retrieve loop change.
        self._index_store: list[_Chunk] = []
        # Counter used to derive stable doc IDs when callers don't supply one.
        self._doc_counter: int = 0

    # ------------------------------------------------------------------
    # RetrievalStrategy interface
    # ------------------------------------------------------------------

    def index(self, documents: list[str]) -> None:
        """
        Chunk and embed each document, appending chunks to the in-memory index.

        Each call *adds* to the existing index — it does not reset it.  This
        mirrors how a real vector DB works (append-only ingestion pipeline).

        Parameters
        ----------
        documents : Raw document strings.  Each string is treated as one
                    logical document and receives a unique parent_doc_id.
        """
        for raw_text in documents:
            self._doc_counter += 1
            doc_id = f"doc-{self._doc_counter}"
            source_uri = f"indexed://{doc_id}"
            chunks = _chunk_document(raw_text, doc_id=doc_id, source_uri=source_uri)
            self._index_store.extend(chunks)

    def retrieve(
        self,
        query: str,
        top_k: int,
        token_budget: int,
    ) -> list[ContextBlock]:
        """
        Return up to *top_k* ContextBlocks whose total token_count ≤ token_budget.

        Algorithm
        ---------
        1. Embed the query with the same mock function used during indexing so
           similarity scores are on a compatible scale.
        2. Compute cosine similarity of the query vector against every stored
           chunk embedding.  O(n·d) dot products — fast enough for thousands of
           chunks in-process; for millions, swap in an ANN library.
        3. Sort by similarity descending, then greedily fill the token budget.

        Parameters
        ----------
        query        : User's natural-language question or task description.
        top_k        : Maximum number of blocks to return (before budget check).
        token_budget : Hard cap on total token_count of returned blocks.

        Returns
        -------
        List of ContextBlock objects ordered by descending relevance_score.
        """
        if not self._index_store:
            # Nothing indexed yet — return empty list rather than crashing.
            return []

        if not query.strip():
            # An empty query would produce a meaningless zero vector; skip retrieval.
            return []

        query_vec = _mock_embedding(query, dim=self._dim)

        # Score every chunk.  We do this in pure Python rather than batched numpy
        # because the list is typically short (< 10k chunks for reference demos).
        # For scale, stack all embeddings into a matrix and do a single matmul.
        scored: list[tuple[float, _Chunk]] = [
            (_cosine_similarity(query_vec, chunk.embedding), chunk)
            for chunk in self._index_store
        ]

        # Sort descending by similarity so we pick the most relevant chunks first.
        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[ContextBlock] = []
        remaining_budget = token_budget

        for sim, chunk in scored[:top_k]:
            # Omit blocks that don't fit — never truncate mid-chunk, as partial
            # context can mislead the model more than no context.
            if chunk.token_count > remaining_budget:
                continue
            results.append(
                ContextBlock(
                    id=chunk.chunk_id,
                    content=chunk.text,
                    source="rag",
                    relevance_score=round(sim, 4),
                    token_count=chunk.token_count,
                    metadata={
                        "source_uri": chunk.source_uri,
                        "chunk_index": chunk.chunk_index,
                        "parent_doc_id": chunk.parent_doc_id,
                    },
                )
            )
            remaining_budget -= chunk.token_count

        return results


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from prefill.interfaces import SystemPromptBuilder

    # A short three-paragraph document about Python async programming.
    SAMPLE_DOC = textwrap.dedent("""\
        Python's asyncio module provides infrastructure for writing single-threaded
        concurrent code using coroutines, multiplexing I/O access over sockets and
        other resources, running network clients and servers, and other related
        primitives. The event loop is the core of every asyncio application.

        The async/await syntax was introduced in Python 3.5 via PEP 492. When you
        mark a function with async def, Python transforms it into a coroutine object.
        The await keyword suspends the current coroutine, yielding control back to
        the event loop so other pending coroutines can run. This cooperative
        multitasking model avoids the overhead of OS thread context switches.

        A common pattern is to use asyncio.gather() to run several coroutines
        concurrently. For example, fetching data from multiple HTTP endpoints
        simultaneously becomes trivial: each request is wrapped in an async function,
        all are passed to gather(), and the event loop drives them to completion.
        Error handling uses standard try/except blocks inside async functions.
    """)

    print("=== RAGStrategy demo ===\n")

    rag = RAGStrategy()
    rag.index([SAMPLE_DOC])

    print(f"Indexed {len(rag._index_store)} chunk(s).\n")

    blocks = rag.retrieve(
        query="how does async/await work",
        top_k=3,
        token_budget=300,
    )

    print(f"Retrieved {len(blocks)} block(s):\n")
    for b in blocks:
        print(f"  [{b.id[:8]}] score={b.relevance_score:.4f}  tokens={b.token_count}")
        print(f"  {b.content[:80]}...")
        print()

    builder = SystemPromptBuilder()
    prompt = builder.build(
        base_prompt="You are a Python expert. Answer clearly.",
        blocks=blocks,
        token_budget=500,
    )
    print("--- Assembled system prompt ---")
    print(prompt)
