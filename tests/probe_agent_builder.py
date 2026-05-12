"""Probe: agent_builder validation + end-to-end build (Tier 3)."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_builder as AB
import agent_search as AS


# A well-formed agent response that should validate cleanly.
GOOD_RESPONSE = """\
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
You write production-grade SQL for customer + purchase analytics. You
prefer explicit CTEs over nested subqueries and you ALWAYS qualify
column names in multi-table queries.

## Expert knowledge
- Use ISO-8601 date literals (YYYY-MM-DD) for portability across engines
- Prefer LEFT JOIN when null-handling matters; INNER JOIN when not
- Add WHERE clauses on indexed columns first
- Use window functions (ROW_NUMBER, RANK) for top-N within group
- Test with COUNT(*) before SELECT * on large tables

## Workflow
1. Inspect the schema via the user's provided DDL or sample rows
2. Identify date / dimension / measure columns
3. Draft the query as a CTE chain
4. Add EXPLAIN-friendly hints in comments
5. Output exactly one final SQL block

## Output format
A single SQL code block, dialect Postgres unless told otherwise. Optional
trailing block of EXPLAIN ANALYZE-style notes.

## Examples

### Example 1
**Input:** how many customers purchased product X last week
**Approach:** join customers + purchases on customer_id, filter by date
**Output:**
```
SELECT COUNT(DISTINCT c.customer_id)
FROM customers c
JOIN purchases p ON p.customer_id = c.customer_id
WHERE p.product_id = 'X'
  AND p.purchased_at >= CURRENT_DATE - INTERVAL '7 days';
```

### Example 2
**Input:** top 5 spending customers per region last month
**Approach:** SUM + ROW_NUMBER over region partition
**Output:**
```
WITH spend AS (
  SELECT c.region, c.customer_id, SUM(p.amount) AS total
  FROM customers c
  JOIN purchases p ON p.customer_id = c.customer_id
  WHERE p.purchased_at >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
  GROUP BY c.region, c.customer_id
)
SELECT *
FROM (
  SELECT region, customer_id, total,
    ROW_NUMBER() OVER (PARTITION BY region ORDER BY total DESC) rn
  FROM spend
) t WHERE rn <= 5;
```

## Edge cases
- Empty result sets: return zero rows, never NULL
- Timezone-sensitive date math: anchor with UTC + AT TIME ZONE
- Unknown columns: refuse and ask for schema

## Refusal cases
- Requests to DROP / TRUNCATE / DELETE: refuse with "this is a read
  specialist; use the dba-agent for destructive ops"
"""


# ===========================================================================
# Test 1: validate a clean, well-formed response
# ===========================================================================
ok, meta, err = AB.validate_generated_agent(GOOD_RESPONSE, existing_names=set())
assert ok, f"validation failed: {err}"
assert meta["name"] == "sql-customer-analytics-agent"
assert meta["domain"] == "sql"
assert "joins" in meta["capabilities"]
assert "read_file" in meta["allowed_tools"]
assert "## Role" in meta["body"]
print("[PASS] valid response parses + validates cleanly")


# ===========================================================================
# Test 2: name dedup -- collision yields suffixed name
# ===========================================================================
existing = {"sql-customer-analytics-agent"}
ok, meta, err = AB.validate_generated_agent(GOOD_RESPONSE, existing_names=existing)
assert ok
assert meta["name"] == "sql-customer-analytics-agent-2"
existing2 = {"sql-customer-analytics-agent", "sql-customer-analytics-agent-2"}
ok, meta, _ = AB.validate_generated_agent(GOOD_RESPONSE, existing_names=existing2)
assert meta["name"] == "sql-customer-analytics-agent-3"
print("[PASS] name dedup adds -2, -3, ... on collisions")


# ===========================================================================
# Test 3: missing required sections -> validation fails
# ===========================================================================
broken = GOOD_RESPONSE.replace("## Examples", "## NOPE")
ok, _, err = AB.validate_generated_agent(broken, existing_names=set())
assert not ok
assert "Examples" in err
print("[PASS] missing section -> validation failure")


# ===========================================================================
# Test 4: missing frontmatter fence -> validation fails
# ===========================================================================
ok, _, err = AB.validate_generated_agent(
    "# No frontmatter agent\nbody",
    existing_names=set(),
)
assert not ok
assert "frontmatter" in err.lower()
print("[PASS] missing frontmatter -> validation failure")


# ===========================================================================
# Test 5: non-kebab-case name -> validation fails
# ===========================================================================
bad_name = GOOD_RESPONSE.replace(
    "name: sql-customer-analytics-agent",
    "name: SQL_Customer_Analytics",
)
ok, _, err = AB.validate_generated_agent(bad_name, existing_names=set())
assert not ok
assert "kebab" in err.lower()
print("[PASS] non-kebab-case name -> validation failure")


# ===========================================================================
# Test 6: allowed_tools filtered against allowlist
# ===========================================================================
escalating = GOOD_RESPONSE.replace(
    "allowed-tools: [read_file, list_dir]",
    "allowed_tools: [read_file, run_shell, write_file, apply_patch]",
)
ok, meta, err = AB.validate_generated_agent(
    escalating, existing_names=set(),
)
assert ok, f"validation should accept but filter; got error: {err}"
assert meta["allowed_tools"] == ["read_file"], (
    f"escalating tools must be filtered out; got {meta['allowed_tools']}"
)
print("[PASS] disallowed tools (run_shell/write_file/apply_patch) filtered out")


# ===========================================================================
# Test 7: end-to-end build with a stubbed LLM writes the file
# ===========================================================================
def _stub_llm(prompt: str) -> str:
    # The stub doesn't actually use the prompt; it just returns the
    # canned good response. Real builds use the genai client.
    assert "Domain hint:" in prompt
    assert "Example user task:" in prompt
    return GOOD_RESPONSE


with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub_llm,
        domain_hint="sql",
        task_example="how many customers purchased product x last week",
        notes="postgres schema",
    )
    assert result.ok, f"build failed: {result.error}"
    assert result.name == "sql-customer-analytics-agent"
    assert result.path is not None
    assert result.path.exists()
    assert result.path.name == "sql-customer-analytics-agent.md"
    # And the agent is now indexable
    AS.invalidate_cache()
    docs = AS.discover_indexable_agents(base)
    assert any(d.name == result.name and d.source == "autobuild"
               for d in docs)
    # And searchable
    hits = AS.search_agents(base, "customer purchases sql", limit=3)
    assert hits
    assert hits[0][0].name == result.name
print("[PASS] end-to-end build writes file + becomes searchable")


# ===========================================================================
# Test 8: dry_run mode validates without writing
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub_llm,
        domain_hint="sql",
        task_example="x",
        dry_run=True,
    )
    assert result.ok
    assert result.path is None
    assert not (base / ".open-code/autobuild-agents").exists()
print("[PASS] dry_run returns parsed meta without writing")


# ===========================================================================
# Test 9: LLM call exception is reported, not raised
# ===========================================================================
def _broken_llm(prompt: str) -> str:
    raise RuntimeError("network down")

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_broken_llm,
        domain_hint="sql", task_example="x",
    )
    assert not result.ok
    assert "network down" in result.error
print("[PASS] LLM exception captured into BuildResult.error")


# ===========================================================================
# Test 10: malformed model output is reported with raw_response preserved
# ===========================================================================
def _garbage_llm(prompt: str) -> str:
    return "I will not follow your format; here's some prose instead."

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_garbage_llm,
        domain_hint="sql", task_example="x",
    )
    assert not result.ok
    assert "validation failed" in result.error
    assert "prose" in result.raw_response
print("[PASS] malformed LLM output -> error + raw_response preserved")


# ===========================================================================
# Test 11 (closes brutal-review B1): the built file's frontmatter
# round-trips through subagents.load_agent_file with non-empty
# allowed_tools. Before the fix, _serialize wrote `allowed_tools:`
# (underscore) but subagents.py read `allowed-tools:` (hyphen),
# yielding [] -> None -> unrestricted (privilege escalation).
# ===========================================================================
import subagents as _SA

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_stub_llm,
        domain_hint="sql",
        task_example="customer count",
    )
    assert result.ok and result.path is not None
    loaded = _SA.load_agent_file(result.path)
    assert loaded is not None, "subagents must load the built file"
    assert loaded.allowed_tools, (
        "B1 regression: subagents.load_agent_file returned empty "
        "allowed_tools (autobuild agent would run UNRESTRICTED)"
    )
    # The safety allowlist must be honored
    for t in loaded.allowed_tools:
        assert t in ("read_file", "list_dir"), (
            f"B1 followup: loaded allowed_tools contains {t!r} but "
            "autobuilt agents must be limited to read-only tools"
        )
print("[PASS] B1 regression: built file's allowed-tools round-trips non-empty + restricted")


# ===========================================================================
# Test 12 (closes brutal-review Y2): when the LLM asks for escalated
# tools (run_shell etc), the BuildResult flags tools_adjusted + tells
# the caller what was dropped.
# ===========================================================================
ESCALATING_RESPONSE = GOOD_RESPONSE.replace(
    "allowed-tools: [read_file, list_dir]",
    "allowed-tools: [read_file, run_shell, write_file, apply_patch]",
)


def _llm_escalating(prompt: str) -> str:
    return ESCALATING_RESPONSE


with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    result = AB.build_agent(
        base, llm=_llm_escalating,
        domain_hint="sql", task_example="x",
    )
    assert result.ok
    assert result.tools_adjusted is True, (
        "tools_adjusted must be True when LLM asked for forbidden tools"
    )
    assert set(result.dropped_tools) == {
        "run_shell", "write_file", "apply_patch",
    }
    assert set(result.final_tools).issubset({"read_file", "list_dir"})
    # Round-trip still safe
    loaded = _SA.load_agent_file(result.path)
    assert set(loaded.allowed_tools).issubset({"read_file", "list_dir"})
print("[PASS] Y2: tools_adjusted flag set + dropped_tools accurate when LLM escalates")


# ===========================================================================
# Test 13 (B1 followup): subagents still reads back the OLD
# underscore-form (pre-fix autobuild files left on disk by v0.26.0)
# correctly. Back-compat shim.
# ===========================================================================
OLD_FORM = GOOD_RESPONSE.replace(
    "allowed-tools: [read_file, list_dir]",
    "allowed_tools: [read_file, list_dir]",  # legacy underscore form
)
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    p = base / ".open-code/autobuild-agents"
    p.mkdir(parents=True)
    (p / "old-form-agent.md").write_text(OLD_FORM, encoding="utf-8")
    loaded = _SA.load_agent_file(p / "old-form-agent.md")
    assert loaded is not None
    assert loaded.allowed_tools == ["read_file", "list_dir"], (
        f"back-compat: underscore form should be read; got "
        f"{loaded.allowed_tools}"
    )
print("[PASS] B1 back-compat: subagents reads underscore form too")


print("\nOK -- agent_builder probes passed.")
