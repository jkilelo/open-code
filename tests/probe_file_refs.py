"""Probe: @-file reference expansion in prompts."""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_code import expand_file_refs, MAX_FILE_REF_BYTES

# Case 1: single ref to existing file
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "README.md").write_text("# my project\nhello world\n", encoding="utf-8")
    prompt = "summarize @README.md please"
    out, refs = expand_file_refs(prompt, base)
    assert len(refs) == 1, f"expected 1 ref, got {len(refs)}"
    assert refs[0]["token"] == "README.md"
    assert "my project" in out
    assert "<file path=" in out
    assert prompt in out  # original prompt preserved
    print(f"[PASS] single ref -> 1 file injected, original prompt preserved")

# Case 2: multiple refs
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "a.txt").write_text("aaa", encoding="utf-8")
    (base / "b.txt").write_text("bbb", encoding="utf-8")
    out, refs = expand_file_refs("compare @a.txt and @b.txt", base)
    assert len(refs) == 2
    assert "aaa" in out and "bbb" in out
    print(f"[PASS] multiple refs -> 2 files injected")

# Case 3: dedup -- same ref twice doesn't double-inject
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "a.txt").write_text("aaa", encoding="utf-8")
    out, refs = expand_file_refs("@a.txt foo @a.txt bar", base)
    assert len(refs) == 1, f"expected dedup, got {len(refs)}"
    print(f"[PASS] dedup -> only one injection for repeated ref")

# Case 4: non-existent ref left as literal
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    out, refs = expand_file_refs("look at @nonexistent.md", base)
    assert refs == []
    assert out == "look at @nonexistent.md"
    print(f"[PASS] missing file -> left as literal, no injection")

# Case 5: URL-ish tokens left alone
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    out, refs = expand_file_refs("see https://example.com/path", base)
    assert refs == []
    print(f"[PASS] URLs not treated as file refs")

# Case 6: trailing punctuation stripped
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "README.md").write_text("hello", encoding="utf-8")
    out, refs = expand_file_refs("summarize @README.md.", base)
    assert len(refs) == 1
    assert refs[0]["token"] == "README.md"
    print(f"[PASS] trailing '.' stripped before resolving")

# Case 7: oversized file truncated
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "big.txt").write_text("x" * (MAX_FILE_REF_BYTES + 5000), encoding="utf-8")
    out, refs = expand_file_refs("read @big.txt", base)
    assert len(refs) == 1
    assert len(refs[0]["content"]) <= MAX_FILE_REF_BYTES + 50
    assert "[...truncated]" in refs[0]["content"]
    print(f"[PASS] oversized file truncated to {len(refs[0]['content'])} chars")

# Case 8: subdirectory path
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    sub = base / "src"
    sub.mkdir()
    (sub / "main.py").write_text("print('hi')", encoding="utf-8")
    out, refs = expand_file_refs("review @src/main.py", base)
    assert len(refs) == 1
    assert "print('hi')" in refs[0]["content"]
    print(f"[PASS] subdirectory path resolved")

print("\nOK -- @-file refs probe complete.")
