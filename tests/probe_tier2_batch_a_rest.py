"""Probe: /compact + extended @-providers (Tier 2 #13 + #19)."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as OC
import sessions as SX


# ===========================================================================
# #13 /compact event semantics in load_history
# ===========================================================================

# ---- Test 1: compact event replaces prior messages with summary ----
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "test compact")
    # Simulate 10 prior msgs + a compact event + 3 recent msgs
    from google.genai import types as _t
    for i in range(10):
        msg = _t.Content(role="user" if i % 2 == 0 else "model",
                         parts=[_t.Part.from_text(text=f"old msg {i}")])
        store.append_message(s, msg)
    store.append_compact(s, summary="Files: a.py, b.py. Decided: use pathlib.",
                         kept_recent=3, dropped=7, model="fake-summarizer")
    for i in range(3):
        msg = _t.Content(role="user" if i % 2 == 0 else "model",
                         parts=[_t.Part.from_text(text=f"recent {i}")])
        store.append_message(s, msg)
    hist, dropped = store.load_history(s, max_messages=0)
    # 10 dropped + 3 recent + 1 summary synthetic = 4 messages now
    assert len(hist) <= 14, f"expected compacted history; got {len(hist)} msgs"
    # First message should be the synthetic summary
    first_text = "".join(
        getattr(p, "text", "") or "" for p in (hist[0].parts or [])
    )
    assert "compacted earlier history" in first_text.lower() or "summary" in first_text.lower()
    assert "use pathlib" in first_text
    # Last messages should be the recent ones
    last_text = "".join(
        getattr(p, "text", "") or "" for p in (hist[-1].parts or [])
    )
    assert "recent" in last_text
    # The 7 oldest msgs should be GONE
    all_concat = " ".join(
        "".join(getattr(p, "text", "") or "" for p in (m.parts or []))
        for m in hist
    )
    assert "old msg 0" not in all_concat
    assert "old msg 6" not in all_concat
print("[PASS] compact event replaces prior msgs with synthetic summary")


# ---- Test 2: no compact event -> behavior unchanged ----
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "no compact")
    from google.genai import types as _t
    for i in range(5):
        msg = _t.Content(role="user" if i % 2 == 0 else "model",
                         parts=[_t.Part.from_text(text=f"plain {i}")])
        store.append_message(s, msg)
    hist, _ = store.load_history(s, max_messages=0)
    assert len(hist) == 5
print("[PASS] sessions without compact: load_history unchanged")


# ===========================================================================
# #19 Extended @-providers
# ===========================================================================

# ---- Test 3: @diff in a real git repo ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    try:
        subprocess.run(["git", "init", "-q", str(base)], check=True)
        subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"],
                       check=True)
        subprocess.run(["git", "-C", str(base), "config", "user.name", "t"],
                       check=True)
        (base / "a.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(base), "add", "."], check=True)
        subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "init"],
                       check=True)
        (base / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[SKIP] git not available; @diff test skipped")
    else:
        out, refs = OC.expand_file_refs("Look at @diff please.", base)
        assert any(r.get("kind") == "provider" and r.get("name") == "diff"
                   for r in refs), f"expected diff provider in refs; got {refs}"
        assert "<context kind=\"diff\">" in out
        assert "world" in out  # new line shows in the diff
        print("[PASS] @diff provider returns git diff content")


# ---- Test 4: @tree provider ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "src").mkdir()
    (base / "src" / "main.py").write_text("print('x')\n")
    (base / "README.md").write_text("# proj\n")
    out, refs = OC.expand_file_refs("Show me @tree", base)
    assert any(r.get("name") == "tree" for r in refs)
    assert "<context kind=\"tree\">" in out
    # The tree output should mention either the dir names or the manual fallback
    tree_content = next(r["content"] for r in refs if r.get("name") == "tree")
    assert "README.md" in tree_content or "src" in tree_content
print("[PASS] @tree returns dir listing")


# ---- Test 5: @cwd provider ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    out, refs = OC.expand_file_refs("My @cwd please", base)
    assert any(r.get("name") == "cwd" for r in refs)
    assert str(base) in out
print("[PASS] @cwd returns absolute CWD path")


# ---- Test 6: @-file refs still work alongside providers ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "README.md").write_text("# my project\n", encoding="utf-8")
    out, refs = OC.expand_file_refs("Summarize @README.md and show @cwd", base)
    kinds = {r.get("kind") for r in refs}
    assert kinds == {"file", "provider"}, f"got kinds={kinds}"
    assert "# my project" in out
    assert str(base) in out
print("[PASS] @-file and @-provider refs coexist")


# ---- Test 7: unknown @-name passes through ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    out, refs = OC.expand_file_refs("Look at @unknown-provider", base)
    assert refs == [], f"unknown provider should NOT inject; got {refs}"
    assert "@unknown-provider" in out  # literal preserved
print("[PASS] unknown @-name left as literal")


print("\nOK -- /compact + extended @-providers probes passed.")
