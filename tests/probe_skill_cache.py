"""Probe: skill prompt caching (Tier 2 #21).

Skills with frontmatter `cache: true` memoize their expanded body
for OPEN_CODE_SKILL_CACHE_TTL seconds (default 300). The cache key
includes the file mtime so an edit invalidates it.

Tests:
  1. Skill without `cache:` flag re-expands every call (volatile cmd
     produces a fresh value each time).
  2. Skill WITH `cache: true` returns the same expansion for the
     same args (volatile cmd not re-run).
  3. Calling with use_cache=False bypasses the cache.
  4. Different args break the cache (each (args, skill) is its own key).
  5. Editing the SKILL.md (changes mtime) invalidates the cache.
"""
from __future__ import annotations
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import skills as SK


SKILL_NO_CACHE = """---
name: tick
description: emit a unique value via date
---
The current ts is !`python -c "import time; print(time.time_ns())"`.
"""

SKILL_CACHED = """---
name: tick_cached
description: emit a unique value via date, cached
cache: true
---
The current ts is !`python -c "import time; print(time.time_ns())"`.
Argument was $ARGUMENTS.
"""


def _write_skill(base: Path, name: str, body: str) -> Path:
    d = base / ".open-code" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(body, encoding="utf-8")
    return p


# ===========================================================================
# Test 1: skill without cache: flag re-expands every call
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "tick", SKILL_NO_CACHE)
    SK.clear_skill_cache()
    sk = SK.find_skill_by_name(base, "tick")
    assert sk is not None
    a = SK.expand_skill_body(sk, "", base)
    b = SK.expand_skill_body(sk, "", base)
    assert a != b, \
        f"expected fresh expansion each call without cache; got identical {a!r}"
print("[PASS] uncached skill re-expands each call")


# ===========================================================================
# Test 2: skill with cache: true returns identical expansions
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "tick_cached", SKILL_CACHED)
    SK.clear_skill_cache()
    sk = SK.find_skill_by_name(base, "tick_cached")
    assert sk is not None
    assert sk.cache is True, "frontmatter cache: true not parsed"
    a = SK.expand_skill_body(sk, "hello", base)
    b = SK.expand_skill_body(sk, "hello", base)
    assert a == b, f"cached skill should return identical; differs:\nA={a!r}\nB={b!r}"
    assert "hello" in a, "args expansion missing"
print("[PASS] cached skill returns identical expansion on second call")


# ===========================================================================
# Test 3: use_cache=False bypasses the cache
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "tick_cached", SKILL_CACHED)
    SK.clear_skill_cache()
    sk = SK.find_skill_by_name(base, "tick_cached")
    a = SK.expand_skill_body(sk, "x", base)  # populates cache
    b = SK.expand_skill_body(sk, "x", base, use_cache=False)
    assert a != b, "use_cache=False should re-expand even when skill.cache=True"
print("[PASS] use_cache=False bypasses the cache")


# ===========================================================================
# Test 4: different args break the cache
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "tick_cached", SKILL_CACHED)
    SK.clear_skill_cache()
    sk = SK.find_skill_by_name(base, "tick_cached")
    a = SK.expand_skill_body(sk, "first", base)
    b = SK.expand_skill_body(sk, "second", base)
    # The args expansion differs ("first" vs "second"), but additionally
    # the cache key differs so the volatile ts is also fresh:
    assert "first" in a and "second" in b
    assert a != b
print("[PASS] different args bypass the cache key")


# ===========================================================================
# Test 5: editing the SKILL.md invalidates the cache
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    p = _write_skill(base, "tick_cached", SKILL_CACHED)
    SK.clear_skill_cache()
    sk = SK.find_skill_by_name(base, "tick_cached")
    a = SK.expand_skill_body(sk, "z", base)
    # Edit + bump mtime forward; reload Skill (mtime captured at load)
    time.sleep(0.05)  # ensure mtime resolution distinguishes
    p.write_text(SKILL_CACHED.replace("$ARGUMENTS", "EDITED-$ARGUMENTS"),
                 encoding="utf-8")
    # Bump mtime explicitly to defeat coarse-grained filesystem timestamps
    import os
    new_mtime = p.stat().st_mtime + 5.0
    os.utime(p, (new_mtime, new_mtime))
    sk2 = SK.find_skill_by_name(base, "tick_cached")
    b = SK.expand_skill_body(sk2, "z", base)
    assert a != b, \
        f"mtime change should invalidate cache; got identical {a!r}"
    assert "EDITED-z" in b
print("[PASS] mtime change invalidates the cache")


print("\nOK -- skill-cache probes passed.")
