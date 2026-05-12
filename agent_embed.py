"""Embedding-based reranker for the agent library.

BM25 is a great first-pass: fast, deterministic, explainable. But it
misses semantic matches -- "find slow queries" won't match an agent
described as "query performance analysis" because there's no token
overlap. Embeddings close that gap.

Strategy: hybrid retrieval.
  1. BM25 returns a fan-out of candidates (top-K, K=10 by default).
  2. We embed the query + each candidate's search_text.
  3. Final rank = alpha * normalized_bm25 + (1 - alpha) * cosine_sim.
     alpha defaults to 0.4 -- semantic similarity weighted slightly
     higher than lexical because the latter already filtered the pool.

Persistence: each agent's embedding lives in a sidecar
`.open-code/autobuild-agents/.embeddings.json` keyed by (name, mtime).
Stale entries (mtime mismatch) are recomputed lazily. Adding a new
agent triggers a single embedding call for that agent only.

Graceful degradation: if the embed function raises (offline, quota,
ImportError), we silently fall back to pure BM25 ranking. The
feature MUST NOT break the base search path.

Math notes:
  - Cosine similarity is computed in pure Python (math.sqrt + sum).
    No numpy dep; the dimensionality of typical embeddings (768 or
    1536) is small enough that this is microseconds for the K
    candidates per query.
  - BM25 scores are min-max normalized to [0, 1] before blending so
    the two components are comparable.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from agent_search import AgentDoc, AUTOBUILD_AGENTS_REL


# Type aliases for clarity
Vector = list[float]
Embedder = Callable[[list[str]], list[Vector]]


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity. Returns 0.0 on zero-norm inputs (safer than NaN)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _min_max_normalize(values: list[float]) -> list[float]:
    """Normalize to [0, 1]. Constant inputs return all-0.5 (neutral)."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ---------------------------------------------------------------------------
# Persistence: .embeddings.json sidecar
# ---------------------------------------------------------------------------


def _sidecar_path(cwd: Path) -> Path:
    return cwd / AUTOBUILD_AGENTS_REL / ".embeddings.json"


def _load_sidecar(cwd: Path) -> dict[str, dict[str, Any]]:
    """Returns {name: {"mtime": float, "vector": [...]}}. Empty on miss."""
    path = _sidecar_path(cwd)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_sidecar(cwd: Path, store: dict[str, dict[str, Any]]) -> None:
    path = _sidecar_path(cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(store, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Sidecar is best-effort. Failing to write means next call will
        # recompute, which is fine.
        pass


def _agent_text_for_embedding(agent: AgentDoc) -> str:
    """The string we embed for an agent. Longer than BM25's search_text:
    we include the body excerpt so semantic match works on a richer
    surface than just keywords."""
    body = agent.extras.get("body", "") if agent.extras else ""
    body_excerpt = body[:1500]  # ~400 tokens, plenty for similarity
    return f"{agent.name}\n{agent.description}\n{agent.domain}\n" + \
           f"{' '.join(agent.capabilities)}\n\n{body_excerpt}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_embeddings(
    cwd: Path,
    agents: list[AgentDoc],
    embedder: Embedder,
) -> dict[str, Vector]:
    """Compute or load embeddings for every agent. Returns {name: vector}.

    Stale entries (mtime drift) are recomputed in a single batch call
    to `embedder`. The sidecar is updated atomically per call.

    On any embedder exception, returns whatever's already cached and
    silently skips the failed batch. The caller's fallback path is to
    rank without embedding contributions.
    """
    sidecar = _load_sidecar(cwd)
    # Y4 fix: prune sidecar entries for agents that no longer exist
    # BEFORE checking which agents are stale. The prior placement of
    # this loop inside `if stale:` meant deleted-agent entries grew
    # unboundedly whenever every remaining agent was fresh.
    current_names = {a.name for a in agents}
    orphans_removed = False
    for stale_key in [k for k in sidecar if k not in current_names]:
        sidecar.pop(stale_key, None)
        orphans_removed = True
    fresh: dict[str, Vector] = {}
    stale: list[AgentDoc] = []
    for a in agents:
        entry = sidecar.get(a.name)
        if entry and abs(entry.get("mtime", 0.0) - a.mtime) < 1e-6:
            vec = entry.get("vector")
            if isinstance(vec, list) and vec:
                fresh[a.name] = vec  # type: ignore[assignment]
                continue
        stale.append(a)
    stale_updates_made = False
    if stale:
        try:
            texts = [_agent_text_for_embedding(a) for a in stale]
            vectors = embedder(texts)
            if len(vectors) != len(stale):
                raise ValueError(
                    f"embedder returned {len(vectors)} vectors for "
                    f"{len(stale)} inputs"
                )
            for a, vec in zip(stale, vectors):
                fresh[a.name] = vec
                sidecar[a.name] = {"mtime": a.mtime, "vector": list(vec)}
            stale_updates_made = True
        except Exception:
            # Fall back: return whatever's already cached.
            pass
    # Persist if EITHER orphans were dropped OR stale entries were
    # recomputed. Without this guard, orphan cleanup would only land
    # on disk when a stale batch coincidentally succeeded.
    if orphans_removed or stale_updates_made:
        _save_sidecar(cwd, sidecar)
    return fresh


def rerank(
    *,
    bm25_results: list[tuple[AgentDoc, float]],
    query: str,
    embeddings: dict[str, Vector],
    query_vector: Vector | None,
    alpha: float = 0.4,
) -> list[tuple[AgentDoc, float]]:
    """Blend BM25 scores with embedding cosine similarity.

    alpha = weight of BM25 in the final score (range 0..1). Default
    0.4 means embeddings get 60% weight, BM25 40% -- the BM25 fan-out
    already concentrated relevance; embedding similarity is the
    discriminator.

    If query_vector is None or embeddings are missing for all
    candidates, returns bm25_results unchanged (pure BM25 ranking).
    """
    if not bm25_results:
        return []
    if query_vector is None or not embeddings:
        return bm25_results
    bm25_scores = [s for _, s in bm25_results]
    bm25_norm = _min_max_normalize(bm25_scores)
    blended: list[tuple[AgentDoc, float]] = []
    for (doc, _), bm_norm in zip(bm25_results, bm25_norm):
        v = embeddings.get(doc.name)
        sem = cosine(query_vector, v) if v is not None else 0.0
        score = alpha * bm_norm + (1.0 - alpha) * sem
        blended.append((doc, score))
    blended.sort(key=lambda x: -x[1])
    return blended


def make_genai_embedder(api_key: str,
                       model: str = "text-embedding-004") -> Embedder:
    """Build an Embedder that calls Google's text-embedding API.

    Returns a function that accepts a list of strings and returns the
    corresponding embedding vectors. The caller is responsible for
    handling exceptions (this function returns the callable; the
    exception surfaces during invocation).
    """
    def _embed(texts: list[str]) -> list[Vector]:
        from google import genai
        client = genai.Client(api_key=api_key)
        # The google-genai SDK exposes embed_content; one call per item
        # is simplest and avoids batch-size constraints. Calls are
        # cheap (sub-second each, parallelizable later).
        out: list[Vector] = []
        for t in texts:
            resp = client.models.embed_content(model=model, contents=t)
            vec = getattr(resp, "embeddings", None)
            if vec and len(vec) > 0:
                values = getattr(vec[0], "values", None)
                if values:
                    out.append(list(values))
                    continue
            out.append([])
        return out
    return _embed


def make_llm_embedder(llm_client: Any,
                      model: str = "text-embedding-004") -> Embedder:
    """Build an Embedder backed by the neutral LLMClient protocol.

    Provider-agnostic: works with any client that implements
    `llm.LLMClient` (Gemini, OpenAI, etc). Embedding model name is
    provider-specific; default is Google's. Override via the
    `settings.autobuild.embedding_model` knob.
    """
    def _embed(texts: list[str]) -> list[Vector]:
        return llm_client.embed(model=model, texts=texts)
    return _embed


def search_hybrid(
    cwd: Path,
    query: str,
    *,
    bm25_results: list[tuple[AgentDoc, float]],
    embedder: Embedder | None,
    alpha: float = 0.4,
) -> list[tuple[AgentDoc, float]]:
    """End-to-end hybrid search. Called by open_code's find_specialist
    when settings.autobuild.semantic_search is enabled."""
    if embedder is None or not bm25_results:
        return bm25_results
    agents = [doc for doc, _ in bm25_results]
    try:
        embeddings = ensure_embeddings(cwd, agents, embedder)
        if not embeddings:
            return bm25_results
        # Embed the query once.
        qvec = embedder([query])
        q = qvec[0] if qvec and qvec[0] else None
    except Exception:
        return bm25_results
    return rerank(
        bm25_results=bm25_results,
        query=query,
        embeddings=embeddings,
        query_vector=q,
        alpha=alpha,
    )
