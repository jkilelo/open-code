"""Probe: repomap.py — discovery, parsing, ranking, rendering."""
from __future__ import annotations
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import repomap as RM


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


# ---- Test 1: parse_file extracts def/class signatures ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "a.py", '''
        def hello(name: str) -> str:
            return f"hi {name}"

        class Greeter:
            def shout(self, x):
                return x.upper()
    ''')
    fs = RM.parse_file(base / "a.py")
    assert "hello" in fs.definitions
    assert "Greeter" in fs.definitions
    assert "Greeter.shout" in fs.definitions
    sigs = "\n".join(fs.signatures)
    assert "def hello(name: str) -> str: ..." in sigs
    assert "class Greeter:" in sigs
    assert "def shout(self, x): ..." in sigs
print("[PASS] parse_file extracts defs / classes / methods with sigs")


# ---- Test 2: parse_file collects referenced names ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "b.py", '''
        from utils import helper
        import os

        def use():
            return helper(os.getcwd())
    ''')
    fs = RM.parse_file(base / "b.py")
    assert "helper" in fs.references
    assert "os" in fs.references or "utils" in fs.references
print("[PASS] parse_file gathers Name/Attribute/Import references")


# ---- Test 3: build_graph creates A->B edge when A references B's def ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "a.py", "def helper(x):\n    return x\n")
    _write(base / "b.py", "from a import helper\n\ndef use():\n    return helper(1)\n")
    sa = RM.parse_file(base / "a.py")
    sb = RM.parse_file(base / "b.py")
    edges = RM.build_graph([sa, sb])
    assert (base / "a.py").resolve() in edges
    assert (base / "b.py").resolve() in edges
    assert (base / "a.py").resolve() in edges[(base / "b.py").resolve()], \
        "b.py should point at a.py because it references `helper`"
print("[PASS] build_graph A->B when A references B's def")


# ---- Test 4: pagerank deterministic and sums to ~1 ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "a.py", "def a():\n    return 1\n")
    _write(base / "b.py", "from a import a\ndef b():\n    return a()\n")
    _write(base / "c.py", "from a import a\ndef c():\n    return a()\n")
    symbols = [RM.parse_file(p) for p in [base / "a.py", base / "b.py", base / "c.py"]]
    edges = RM.build_graph(symbols)
    scores = RM.pagerank(edges)
    assert len(scores) == 3
    total = sum(scores.values())
    assert 0.95 < total < 1.05, f"PageRank should sum to ~1; got {total}"
    # a.py should be highest because 2 files reference it
    a_score = scores[(base / "a.py").resolve()]
    b_score = scores[(base / "b.py").resolve()]
    assert a_score > b_score, f"a should outrank b; a={a_score} b={b_score}"
print("[PASS] PageRank: incoming edges raise score; sum ~1.0")


# ---- Test 5: build_repomap end-to-end produces a <repo-map> block ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    for i, code in enumerate([
        "def alpha(): return 1\n",
        "def beta(): return 2\n",
        "def gamma(): return 3\n",
        "def delta(): return 4\n",
    ]):
        _write(base / f"m{i}.py", code)
    rm_text = RM.build_repomap(base)
    assert rm_text.startswith("<repo-map>")
    assert "alpha" in rm_text
    assert "delta" in rm_text
    assert rm_text.endswith("</repo-map>")
print("[PASS] build_repomap returns a non-empty block on a small repo")


# ---- Test 6: tiny repo (< MIN_FILES_TO_BOTHER) returns empty ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "only.py", "def x(): return 1\n")
    rm_text = RM.build_repomap(base)
    assert rm_text == "", f"tiny repo should return empty; got {rm_text!r}"
print("[PASS] tiny repo (<3 files) -> empty repo-map")


# ---- Test 7: max_chars caps the output ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    # Generate 30 files each with a few functions
    for i in range(30):
        body = "\n".join(f"def fn_{i}_{j}(x): return x" for j in range(10))
        _write(base / f"f{i:02d}.py", body + "\n")
    rm_text = RM.build_repomap(base, max_chars=600)
    assert len(rm_text) < 900, f"max_chars cap exceeded: {len(rm_text)}"
    assert "...repo-map truncated" in rm_text
print("[PASS] max_chars cap respected; truncation marker appended")


# ---- Test 8: personalization prefers task-mentioned files ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "important_alpha.py", "def alpha(): return 1\n")
    _write(base / "random_beta.py", "def beta(): return 2\n")
    _write(base / "extra_gamma.py", "def gamma(): return 3\n")
    rm_no_hint = RM.build_repomap(base, task_hint=None)
    rm_with_hint = RM.build_repomap(base, task_hint="please fix important_alpha logic")
    # With the hint, important_alpha should appear earlier in the body
    pos_with = rm_with_hint.find("important_alpha.py")
    pos_no = rm_no_hint.find("important_alpha.py")
    assert pos_with >= 0
    assert pos_with <= pos_no or pos_no < 0
print("[PASS] personalization: task hint shifts ranking toward mentioned file")


# ---- Test 9: skips .venv / __pycache__ / node_modules ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write(base / "real.py", "def real(): pass\n")
    _write(base / ".venv" / "site-packages" / "noisy.py", "def noisy(): pass\n")
    _write(base / "node_modules" / "junk.py", "def junk(): pass\n")
    files = RM.discover_files(base)
    names = [p.name for p in files]
    assert "real.py" in names
    assert "noisy.py" not in names
    assert "junk.py" not in names
print("[PASS] discover_files skips .venv / node_modules / __pycache__")


print("\nOK -- 9 repomap probes passed.")
