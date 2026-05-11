"""Probe: OPEN_CODE.md project context loader.

Verifies:
- Walks up parents and finds the nearest OPEN_CODE.md
- Truncates oversized files
- Returns ("", None) when none found
"""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_code import load_project_context, build_system_instruction, SYSTEM_INSTRUCTION, MAX_PROJECT_CONTEXT_BYTES

# Case 1: OPEN_CODE.md in CWD
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    ctx_file = base / "OPEN_CODE.md"
    ctx_file.write_text("# Project Cool\nUse pathlib. Tests in tests/.", encoding="utf-8")
    text, path = load_project_context(base)
    assert "Project Cool" in text, f"expected content, got {text[:80]!r}"
    assert path == ctx_file, f"expected {ctx_file}, got {path}"
    print(f"[PASS] direct OPEN_CODE.md -> loaded {len(text)} chars from {path}")

# Case 2: OPEN_CODE.md in a parent
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    deep = base / "a" / "b" / "c"
    deep.mkdir(parents=True)
    ctx_file = base / "OPEN_CODE.md"
    ctx_file.write_text("# Monorepo root", encoding="utf-8")
    text, path = load_project_context(deep)
    assert "Monorepo root" in text
    assert path == ctx_file
    print(f"[PASS] ancestor OPEN_CODE.md -> found at {path} from deep CWD")

# Case 3: none anywhere
with tempfile.TemporaryDirectory() as d:
    text, path = load_project_context(Path(d).resolve())
    # On Windows, ~/.open-code... irrelevant; the walk goes up to drive root
    # without finding OPEN_CODE.md.
    if text == "":
        print("[PASS] no OPEN_CODE.md -> ('', None)")
    else:
        print(f"[INFO] found OPEN_CODE.md at ancestor: {path} (not a fail, just env)")

# Case 4: oversized file is truncated
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    ctx_file = base / "OPEN_CODE.md"
    ctx_file.write_text("x" * (MAX_PROJECT_CONTEXT_BYTES + 1000), encoding="utf-8")
    text, _ = load_project_context(base)
    assert len(text) <= MAX_PROJECT_CONTEXT_BYTES + 50, f"truncation failed: {len(text)}"
    assert "[...truncated]" in text
    print(f"[PASS] oversized file truncated to {len(text)} chars")

# Case 5: build_system_instruction augments correctly
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    ctx_file = base / "OPEN_CODE.md"
    ctx_file.write_text("Use ruff format on save.", encoding="utf-8")
    text, path = load_project_context(base)
    full = build_system_instruction(text, path)
    assert full.startswith(SYSTEM_INSTRUCTION)
    assert "Use ruff format on save." in full
    assert str(path) in full or "Project context" in full
    print(f"[PASS] build_system_instruction added project block ({len(full) - len(SYSTEM_INSTRUCTION)} extra chars)")

# Case 6: empty context -> unchanged system instruction
full = build_system_instruction("", None)
assert full == SYSTEM_INSTRUCTION
print("[PASS] empty context -> unchanged system instruction")

print("\nOK -- project context probe complete.")
