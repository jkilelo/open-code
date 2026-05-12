"""Live LSP smoke against real pyright-langserver.

Requires: pip install pyright

Tests the four LSP tools against an actual language server on a
fresh Python file in a tempdir. The file is deliberately crafted
to surface a type error pyright will flag, plus a function
def + use so hover/definition/references have something to chew on.
"""
from __future__ import annotations
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lsp import LSPClient

pyright = shutil.which("pyright-langserver")
assert pyright, "pyright-langserver not on PATH -- run: pip install pyright"


SAMPLE = textwrap.dedent('''\
"""Sample for the LSP smoke test."""


def add(a: int, b: int) -> int:
    return a + b


def main() -> None:
    # Line 7: a type error pyright will flag.
    bad: int = "not an integer"
    # Line 9: a use of add() -- references should find here + line 12.
    result = add(1, 2)
    print(result, bad)
    print(add(3, 4))


if __name__ == "__main__":
    main()
''')


with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    target = base / "sample.py"
    target.write_text(SAMPLE, encoding="utf-8")

    client = LSPClient(cwd=base)
    client.configure({
        "enabled": True,
        "servers": {
            "python": {
                "command": pyright,
                "args": ["--stdio"],
                "file_patterns": ["*.py", "*.pyi"],
            },
        },
    })

    try:
        # ---- 1. Diagnostics ----
        r = client.lsp_diagnostics(str(target))
        assert r["ok"], r
        diags = r["diagnostics"]
        # Pyright should flag the str-vs-int assignment on the line
        # `bad: int = "not an integer"` (line index 8 in 0-indexed).
        err_lines = [d["line"] for d in diags if d["severity"] == "error"]
        print(f"[PASS] diagnostics: {len(diags)} entries, errors at lines {err_lines}")
        assert any(d["severity"] == "error" for d in diags), (
            f"expected pyright to report a type error; got: {diags}"
        )

        # ---- 2. Hover on `add` use (line 10, col ~13 in 'result = add(1, 2)') ----
        # Find the line ourselves so we don't fight pyright's exact indexing
        lines = SAMPLE.splitlines()
        for i, line in enumerate(lines):
            if "result = add" in line:
                hover_line = i
                hover_col = line.index("add") + 1  # mid-symbol
                break
        else:
            raise AssertionError("could not find result = add in sample")
        r = client.lsp_hover(str(target), hover_line, hover_col)
        assert r["ok"], r
        text = r["text"]
        # Hover should mention the signature; pyright formats it as
        # "(function) def add(a: int, b: int) -> int" or similar.
        assert "add" in text and ("int" in text or "(a:" in text), (
            f"hover text didn't look like a fn signature: {text!r}"
        )
        print(f"[PASS] hover at line {hover_line} col {hover_col}: "
              f"{text.splitlines()[0][:80]!r}")

        # ---- 3. Definition of `add` use jumps back to its def ----
        r = client.lsp_definition(str(target), hover_line, hover_col)
        assert r["ok"], r
        locs = r["locations"]
        assert locs, f"definition came back empty: {r}"
        # Pyright should point at the `def add(...)` line (index 3).
        def_lines = [loc["line"] for loc in locs]
        assert 3 in def_lines, f"expected def at line 3; got {def_lines}"
        print(f"[PASS] definition jumps to lines {def_lines}")

        # ---- 4. References to `add` -- the def + 2 calls ----
        # Position at the DEF this time so we get all callers.
        def_col = lines[3].index("add") + 1
        r = client.lsp_references(str(target), 3, def_col)
        assert r["ok"], r
        ref_lines = sorted({loc["line"] for loc in r["locations"]})
        # Expect at least 2 lines (typically the def + the 2 use sites)
        assert len(ref_lines) >= 2, (
            f"expected >=2 reference lines; got {ref_lines}"
        )
        print(f"[PASS] references found {len(r['locations'])} usages "
              f"across lines {ref_lines}")

    finally:
        client.shutdown()

print("\nOK -- live pyright LSP smoke verified.")
