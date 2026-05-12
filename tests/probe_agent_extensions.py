"""Probe: v0.26.1 extensions -- embeddings + versioning + approval flow."""
from __future__ import annotations
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_builder as AB
import agent_embed as AE
import agent_search as AS
import subagents as SA


# Reused good response (hyphen form)
GOOD = """\
---
name: sql-customer-analytics-agent
description: Writes precise SQL queries for customer purchase analytics with proper joins and date filtering
domain: sql
capabilities: [sql, analytics, customers, purchases, joins, postgres]
allowed-tools: [read_file, list_dir]
model: null
---

# SQL Customer Analytics Agent

## Role
You write production-grade SQL.

## Expert knowledge
- Use ISO-8601 date literals
- Prefer LEFT JOIN when null-handling matters
- Add WHERE clauses on indexed columns first

## Workflow
1. Inspect schema
2. Draft as CTE chain

## Output format
Single SQL block.

## Examples

### Example 1
**Input:** count customers
**Approach:** simple
**Output:** SELECT count(*) FROM customers;

## Edge cases
- empty results

## Refusal cases
- destructive ops
"""


def _stub(prompt: str) -> str:
    return GOOD


# ===========================================================================
# Test 1: auto_approve=True writes to live dir (default behavior)
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub,
        domain_hint="sql", task_example="customer count",
        auto_approve=True,
    )
    assert result.ok
    assert result.path is not None
    assert result.path.parent.name == "autobuild-agents"
    assert ".pending" not in str(result.path)
print("[PASS] auto_approve=True writes to live autobuild-agents/")


# ===========================================================================
# Test 2: auto_approve=False routes to .pending/
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub,
        domain_hint="sql", task_example="x",
        auto_approve=False,
    )
    assert result.ok
    assert result.path is not None
    assert ".pending" in str(result.path)
    pending = AB.list_pending(base)
    assert len(pending) == 1
    assert pending[0].stem == result.name
    # And NOT yet searchable (not in live dir)
    AS.invalidate_cache()
    hits = AS.search_agents(base, "customer sql analytics", limit=5)
    assert not any(h[0].name == result.name for h in hits)
print("[PASS] auto_approve=False routes to .pending/ + invisible to search")


# ===========================================================================
# Test 3: approve_pending promotes pending -> live + invalidates cache
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub,
        domain_hint="sql", task_example="x",
        auto_approve=False,
    )
    assert result.ok
    name = result.name
    ok, msg, live = AB.approve_pending(base, name)
    assert ok, msg
    assert live is not None
    assert ".pending" not in str(live)
    assert live.is_file()
    # Pending is now empty
    assert not AB.list_pending(base)
    # Searchable
    AS.invalidate_cache()
    hits = AS.search_agents(base, "customer sql analytics", limit=5)
    assert any(h[0].name == name for h in hits)
print("[PASS] approve_pending promotes to live + becomes searchable")


# ===========================================================================
# Test 4: reject_pending deletes without promoting
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub, domain_hint="sql", task_example="x",
        auto_approve=False,
    )
    assert result.ok
    name = result.name
    ok, msg = AB.reject_pending(base, name)
    assert ok, msg
    assert not AB.list_pending(base)
    # And the live dir doesn't contain it
    AS.invalidate_cache()
    hits = AS.search_agents(base, "customer sql analytics", limit=5)
    assert not any(h[0].name == name for h in hits)
print("[PASS] reject_pending discards without promoting")


# ===========================================================================
# Test 5: building a same-named agent twice archives the first version
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    r1 = AB.build_agent(base, llm=_stub, task_example="x",
                          auto_approve=True)
    assert r1.ok
    # Manually re-write the same name (simulating revert + rebuild)
    live = base / ".open-code/autobuild-agents" / f"{r1.name}.md"
    versions_before = AB.list_versions(base, r1.name)
    # The first build was on a fresh dir, so no archive yet:
    assert len(versions_before) == 0
    # Now write a new version manually + trigger archive via revert path
    new_content = live.read_text(encoding="utf-8").replace(
        "Writes precise SQL", "VERSION 2"
    )
    AB._archive_existing(base, r1.name, live)
    live.write_text(new_content, encoding="utf-8")
    versions_after = AB.list_versions(base, r1.name)
    assert len(versions_after) == 1, (
        f"expected 1 archived version; got {len(versions_after)}"
    )
print("[PASS] _archive_existing copies live -> .history/<name>/<ts>.md")


# ===========================================================================
# Test 6: revert_to_version restores the most recent version
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    r1 = AB.build_agent(base, llm=_stub, task_example="x",
                          auto_approve=True)
    name = r1.name
    live = base / ".open-code/autobuild-agents" / f"{name}.md"
    # Archive original + write a "broken" replacement
    AB._archive_existing(base, name, live)
    broken_text = live.read_text(encoding="utf-8").replace(
        "Writes precise SQL", "BROKEN VERSION"
    )
    time.sleep(0.02)
    live.write_text(broken_text, encoding="utf-8")
    # Sanity: live now says BROKEN
    assert "BROKEN VERSION" in live.read_text(encoding="utf-8")
    # Revert
    ok, msg = AB.revert_to_version(base, name)
    assert ok, msg
    restored = live.read_text(encoding="utf-8")
    assert "BROKEN VERSION" not in restored
    assert "Writes precise SQL" in restored
    # And the revert itself archived the broken version, so we can
    # roll forward
    versions = AB.list_versions(base, name)
    assert len(versions) >= 2
print("[PASS] revert_to_version restores prior + archives outgoing")


# ===========================================================================
# Test 7: revert with unknown ts-prefix fails cleanly
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    r1 = AB.build_agent(base, llm=_stub, task_example="x",
                          auto_approve=True)
    ok, msg = AB.revert_to_version(base, r1.name, "9999-12-31")
    assert not ok
    assert "no" in msg.lower()
print("[PASS] revert with unknown timestamp prefix fails cleanly")


# ===========================================================================
# Test 8: cosine similarity on equal vectors == 1.0
# ===========================================================================
v = [0.1, 0.2, -0.3, 0.5]
assert abs(AE.cosine(v, v) - 1.0) < 1e-9
# Orthogonal -> 0
assert abs(AE.cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
# Anti-parallel -> -1
assert abs(AE.cosine([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-9
# Zero vector -> 0 (no NaN)
assert AE.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
# Empty -> 0
assert AE.cosine([], []) == 0.0
print("[PASS] cosine similarity: identical=1, orthogonal=0, anti=-1, zero=0")


# ===========================================================================
# Test 9: rerank with a stub embedder pulls semantic matches up
# ===========================================================================
# Three agents. BM25 ranks B first because of keyword overlap, but
# the query is semantically about A. A stub embedder simulates that.
def _stub_emb_factory(query_text: str):
    """Build an embedder where the query is closer to 'A' than to 'B'."""
    def _emb(texts):
        out = []
        for t in texts:
            if "alpha" in t:
                out.append([1.0, 0.0, 0.0])
            elif "beta" in t:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])  # query and others
        return out
    return _emb

# Build a fake BM25 result list:
agents = [
    AS.AgentDoc(name="alpha-agent", description="alpha specialist",
                capabilities=["alpha"], mtime=1.0),
    AS.AgentDoc(name="beta-agent", description="beta specialist",
                capabilities=["beta"], mtime=2.0),
]
bm25 = [(agents[1], 2.0), (agents[0], 1.0)]  # BM25 says beta wins
# Query embedding is closer to alpha
emb_dict = {"alpha-agent": [1.0, 0.0, 0.0],
            "beta-agent": [0.0, 1.0, 0.0]}
qvec = [0.9, 0.1, 0.0]  # mostly alpha-ish
reranked = AE.rerank(
    bm25_results=bm25, query="alpha", embeddings=emb_dict,
    query_vector=qvec, alpha=0.3,  # 30% BM25, 70% semantic
)
assert reranked[0][0].name == "alpha-agent", (
    f"semantic rerank should put alpha first; got {[r[0].name for r in reranked]}"
)
print("[PASS] rerank: semantic similarity overrides BM25 when alpha is low")


# ===========================================================================
# Test 10: rerank degrades to BM25 ordering when query_vector is None
# ===========================================================================
out = AE.rerank(
    bm25_results=bm25, query="alpha",
    embeddings=emb_dict, query_vector=None,
)
# Same order as bm25 input
assert [r[0].name for r in out] == [r[0].name for r in bm25]
print("[PASS] rerank with query_vector=None returns bm25 ordering")


# ===========================================================================
# Test 11: search_hybrid falls back to BM25 when embedder raises
# ===========================================================================
def _broken_embed(texts):
    raise RuntimeError("offline")

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    p = base / ".open-code/agents"
    p.mkdir(parents=True)
    (p / "sql-query-agent.md").write_text(
        "---\nname: sql-query-agent\ndescription: SQL writer\n"
        "capabilities: [sql]\n---\nbody\n", encoding="utf-8"
    )
    AS.invalidate_cache()
    bm25 = AS.search_agents(base, "sql", limit=5)
    out = AE.search_hybrid(
        base, "sql", bm25_results=bm25, embedder=_broken_embed,
    )
    # Falls back, returns same content
    assert [r[0].name for r in out] == [r[0].name for r in bm25]
print("[PASS] search_hybrid swallows embedder exception, returns BM25 result")


# ===========================================================================
# Test 12: embedding sidecar caches and reuses across calls
# ===========================================================================
calls = {"n": 0}
def _counting_emb(texts):
    calls["n"] += 1
    return [[float(i + 1)] for i, _ in enumerate(texts)]

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    p = base / ".open-code/autobuild-agents"
    p.mkdir(parents=True)
    (p / "x-agent.md").write_text(
        "---\nname: x-agent\ndescription: thing\n"
        "capabilities: [a, b]\n---\nbody\n", encoding="utf-8"
    )
    AS.invalidate_cache()
    agents = AS.discover_indexable_agents(base)
    e1 = AE.ensure_embeddings(base, agents, _counting_emb)
    assert "x-agent" in e1
    assert calls["n"] == 1
    # Second call: cache hit, no new embedder call
    e2 = AE.ensure_embeddings(base, agents, _counting_emb)
    assert calls["n"] == 1
    assert e2["x-agent"] == e1["x-agent"]
    # Sidecar on disk
    side = base / ".open-code/autobuild-agents" / ".embeddings.json"
    assert side.is_file()
    data = json.loads(side.read_text(encoding="utf-8"))
    assert "x-agent" in data
print("[PASS] ensure_embeddings caches via sidecar across calls")


print("\nOK -- agent extensions probes passed.")
