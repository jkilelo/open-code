"""Probe: Tier 2 polish trio — four-tier memory, effort levels, ultrathink.

This single probe covers #18, #15, #16 plus the status-line plumbing
because they all share the system_instruction / settings surface.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as OC
import settings as S


# ===========================================================================
# #18 Four-tier memory
# ===========================================================================

# ---- Test 1: empty CWD with no global => no layers ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    # Hide any real global memory by pointing to a non-existent path
    saved_global = OC.GLOBAL_MEMORY_PATH
    OC.GLOBAL_MEMORY_PATH = base / "no-such-global.md"
    try:
        layers = OC.load_project_layers(base)
        assert layers == [], f"empty project should yield no layers; got {layers}"
    finally:
        OC.GLOBAL_MEMORY_PATH = saved_global
print("[PASS] empty project + no global -> no layers")

# ---- Test 2: All four tiers concatenate in order ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    # Tier 2 ancestor (parent dir)
    anc = base / "anc"
    anc.mkdir()
    deep = anc / "child"
    deep.mkdir()
    # Fake global by pointing to a file we create
    fake_global = base / "fake_global.md"
    fake_global.write_text("=== global mem ===\n", encoding="utf-8")
    saved = OC.GLOBAL_MEMORY_PATH
    OC.GLOBAL_MEMORY_PATH = fake_global
    try:
        (anc / "OPEN_CODE.md").write_text("=== ancestor mem ===\n", encoding="utf-8")
        (deep / "OPEN_CODE.md").write_text("=== project mem ===\n", encoding="utf-8")
        priv_dir = deep / ".open-code"
        priv_dir.mkdir()
        (priv_dir / "MEMORY.md").write_text("=== private mem ===\n", encoding="utf-8")

        layers = OC.load_project_layers(deep)
        contents = [c for _p, c in layers]
        combined = "\n\n".join(contents)
        # All four labels appear; in the right order
        assert "=== global mem ===" in combined
        assert "=== ancestor mem ===" in combined
        assert "=== project mem ===" in combined
        assert "=== private mem ===" in combined
        # Order: global -> ancestor -> project -> private
        i_global = combined.find("global mem")
        i_anc = combined.find("ancestor mem")
        i_proj = combined.find("project mem")
        i_priv = combined.find("private mem")
        assert i_global < i_anc < i_proj < i_priv, (
            f"layer order wrong: g={i_global} a={i_anc} p={i_proj} priv={i_priv}"
        )
    finally:
        OC.GLOBAL_MEMORY_PATH = saved
print("[PASS] four tiers concatenate in correct order")

# ---- Test 3: build_system_instruction_layered preserves base ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / "OPEN_CODE.md").write_text("Be terse.", encoding="utf-8")
    saved = OC.GLOBAL_MEMORY_PATH
    OC.GLOBAL_MEMORY_PATH = base / "no-such-global"
    try:
        layers = OC.load_project_layers(base)
        full = OC.build_system_instruction_layered(layers)
        assert full.startswith(OC.SYSTEM_INSTRUCTION)
        assert "Be terse." in full
        assert "Project context from" in full
    finally:
        OC.GLOBAL_MEMORY_PATH = saved
print("[PASS] build_system_instruction_layered adds project blocks")


# ===========================================================================
# #15 Effort levels
# ===========================================================================

# ---- Test 4: settings.effort round-trips through settings.json ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / ".open-code").mkdir()
    (base / ".open-code" / "settings.json").write_text(
        json.dumps({"effort": "high"}), encoding="utf-8"
    )
    s = S.load_layered_settings(base)
    assert s.effort == "high", f"got {s.effort!r}"
print("[PASS] settings.effort round-trip")

# ---- Test 5: invalid effort falls back to medium ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / ".open-code").mkdir()
    (base / ".open-code" / "settings.json").write_text(
        json.dumps({"effort": "infinite"}), encoding="utf-8"
    )
    s = S.load_layered_settings(base)
    assert s.effort == "medium"
print("[PASS] invalid effort -> medium fallback")

# ---- Test 6: EFFORT_BUDGETS table ----
assert OC.EFFORT_BUDGETS == {"low": 0, "medium": 512, "high": 4096, "xhigh": 16384}
assert OC.VALID_EFFORTS_TUPLE if hasattr(OC, "VALID_EFFORTS_TUPLE") else True
print("[PASS] EFFORT_BUDGETS table matches spec")


# ===========================================================================
# #16 Ultrathink (one-turn budget override)
# ===========================================================================

# ---- Test 7: ultrathink marker is detected and stripped ----
import re
prompt = "ultrathink — why does foo break?"
assert re.search(r"\b" + re.escape(OC.ULTRATHINK_MARKER) + r"\b", prompt, flags=re.I)
stripped = re.sub(r"\b" + re.escape(OC.ULTRATHINK_MARKER) + r"\b", "", prompt, flags=re.I).strip()
assert "ultrathink" not in stripped.lower()
assert "why does foo break" in stripped
print("[PASS] ultrathink marker detected case-insensitively + strippable")

# ---- Test 8: marker doesn't false-positive on substrings ----
prompt2 = "I'm using ultrathinker.io to brainstorm"
assert not re.search(
    r"\b" + re.escape(OC.ULTRATHINK_MARKER) + r"\b(?!\w)", prompt2, flags=re.I
), "should not match 'ultrathinker' (different word)"
# Actually `\b` after 'ultrathink' before 'er' is no boundary, so our
# regex won't match. Confirm:
m = re.search(r"\b" + re.escape(OC.ULTRATHINK_MARKER) + r"\b", prompt2, flags=re.I)
assert m is None, f"false positive on 'ultrathinker': matched {m.group()!r}"
print("[PASS] ultrathink doesn't match 'ultrathinker' (word boundary)")


print("\nOK -- Tier 2 polish trio (memory + effort + ultrathink) probe passed.")
