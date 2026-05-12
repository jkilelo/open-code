"""Probe: BM25 search over the agent library (Tier 3)."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_search as AS


SQL_AGENT = """---
name: sql-query-agent
description: Writes optimized SQL queries for analytics over relational tables
domain: sql
capabilities: [sql, query, analytics, postgres, joins]
allowed_tools: [read_file, list_dir]
---
# SQL Query Agent
## Role
You write SQL.
## Expert knowledge
- Prefer CTEs over subqueries.
## Workflow
1. Read schema.
## Output format
Single SQL block.
## Examples
### Example 1
**Input:** count customers
**Approach:** simple aggregate
**Output:** SELECT count(*) FROM customers;
"""

WEB_AGENT = """---
name: web-scraper-agent
description: Scrapes javascript-rendered web pages and extracts structured data
domain: web
capabilities: [scraping, playwright, html, javascript, extraction]
allowed_tools: [read_file]
---
# Web scraper
## Role
You scrape.
## Expert knowledge
- Respect robots.txt.
## Workflow
1. Inspect page.
## Output format
JSON records.
## Examples
### Example 1
**Input:** scrape this URL
**Approach:** fetch then parse
**Output:** [{...}]
"""

ML_AGENT = """---
name: ml-baseline-agent
description: Builds simple machine learning baselines for tabular classification
domain: ml
capabilities: [ml, classification, sklearn, baseline, features]
allowed_tools: [read_file, list_dir]
---
# ML baseline
## Role
You build baselines.
## Expert knowledge
- Always try logistic regression first.
## Workflow
1. Load data.
## Output format
Python script.
## Examples
### Example 1
**Input:** classify churn
**Approach:** lr baseline
**Output:** from sklearn import...
"""


def _make_lib(base: Path,
              files: dict[str, str], folder: str = ".open-code/agents") -> Path:
    d = base / folder
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


# ===========================================================================
# Test 1: tokenizer drops stopwords + short tokens
# ===========================================================================
toks = AS.tokenize("The quick brown fox is in the JSON")
assert "the" not in toks
assert "is" not in toks
assert "in" not in toks
# 'a' would also be a stopword but isn't in the input.
# Length-1 tokens dropped too:
toks2 = AS.tokenize("x is a y, but z works")
assert "x" not in toks2
assert "y" not in toks2
assert "z" not in toks2
# 'works' survives
assert "works" in toks2
# 'json' is uppercased in input -> lowercased
assert "json" in toks
print("[PASS] tokenize lowercases, drops stopwords + 1-char tokens")


# ===========================================================================
# Test 2: BM25 ranks the right doc on top
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _make_lib(base, {
        "sql-query-agent.md": SQL_AGENT,
        "web-scraper-agent.md": WEB_AGENT,
        "ml-baseline-agent.md": ML_AGENT,
    })
    AS.invalidate_cache()
    hits = AS.search_agents(base, "sql query customer count", limit=3)
    assert hits, "expected at least one match for an SQL query"
    top = hits[0][0]
    assert top.name == "sql-query-agent", f"got {top.name}"
    # Score should be positive and the runner-up should be lower
    assert hits[0][1] > 0
    if len(hits) > 1:
        assert hits[0][1] > hits[1][1]
print("[PASS] BM25 ranks sql-agent #1 for an SQL query")


# ===========================================================================
# Test 3: query targeting a different domain ranks that domain's agent first
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _make_lib(base, {
        "sql-query-agent.md": SQL_AGENT,
        "web-scraper-agent.md": WEB_AGENT,
        "ml-baseline-agent.md": ML_AGENT,
    })
    AS.invalidate_cache()
    hits = AS.search_agents(base, "scrape javascript pages", limit=3)
    assert hits[0][0].name == "web-scraper-agent"
print("[PASS] BM25 ranks web-scraper #1 for a scraping query")


# ===========================================================================
# Test 4: empty library -> empty results, no crash
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    AS.invalidate_cache()
    hits = AS.search_agents(base, "anything", limit=5)
    assert hits == []
print("[PASS] empty library returns []")


# ===========================================================================
# Test 5: terms with zero matches don't crash; partial matches OK
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _make_lib(base, {"sql-query-agent.md": SQL_AGENT})
    AS.invalidate_cache()
    # zzzzz doesn't appear anywhere; sql does
    hits = AS.search_agents(base, "zzzzz sql nonexistent", limit=3)
    assert len(hits) == 1
    assert hits[0][0].name == "sql-query-agent"
print("[PASS] unknown query terms ignored; matching terms still rank")


# ===========================================================================
# Test 6: autobuild folder is also indexed; user folder shadows on name
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    # Put autobuild version
    _make_lib(base, {
        "sql-query-agent.md": SQL_AGENT.replace(
            "Writes optimized SQL", "AUTOBUILD VERSION"),
    }, folder=".open-code/autobuild-agents")
    # And a user-curated version with same name
    _make_lib(base, {
        "sql-query-agent.md": SQL_AGENT,
    }, folder=".open-code/agents")
    AS.invalidate_cache()
    docs = AS.discover_indexable_agents(base)
    assert len(docs) == 1
    # User version (source="user") wins
    assert docs[0].source == "user"
    assert "AUTOBUILD VERSION" not in docs[0].description
print("[PASS] user-curated agent shadows autobuild on name collision")


# ===========================================================================
# Test 7: cache invalidates on file mtime change
# ===========================================================================
import time as _time
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    p = base / ".open-code/agents"
    p.mkdir(parents=True)
    f = p / "sql-query-agent.md"
    f.write_text(SQL_AGENT, encoding="utf-8")
    AS.invalidate_cache()
    idx1 = AS.get_index(base)
    # Edit + bump mtime
    _time.sleep(0.02)
    import os
    new_mtime = f.stat().st_mtime + 5.0
    f.write_text(SQL_AGENT.replace("SQL", "SQL-EDITED"), encoding="utf-8")
    os.utime(f, (new_mtime, new_mtime))
    idx2 = AS.get_index(base)
    # Different index objects -> rebuilt
    assert idx1 is not idx2
print("[PASS] cache rebuilds on mtime change")


print("\nOK -- agent_search probes passed.")
