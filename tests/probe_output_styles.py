"""Probe: output styles (Tier 2 #23).

Tests:
  - All built-in styles resolve to non-empty overlays (except `default`)
  - apply_to_system_instruction appends the overlay under a header
  - "default" is a no-op (returns base unchanged)
  - Custom project styles override built-in names
  - Custom user styles work
  - Unknown style names produce empty overlay (no crash)
  - settings.output_style propagates from settings.json
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import output_styles as OS
import settings as S


# ===========================================================================
# Test 1: built-in styles have non-empty overlays except "default"
# ===========================================================================
for name, body in OS.BUILTIN_STYLES.items():
    if name == "default":
        assert body == "", f"default should be empty; got {body[:40]!r}"
    else:
        assert body.strip(), f"built-in {name!r} has empty overlay"
        assert len(body) >= 40, f"built-in {name!r} seems too short"
print("[PASS] built-in styles non-empty except 'default'")


# ===========================================================================
# Test 2: apply_to_system_instruction appends under a header
# ===========================================================================
base = "You are a coding agent."
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    out, source = OS.apply_to_system_instruction(base, "concise", cwd)
    assert out.startswith(base)
    assert "## Output style: concise" in out
    assert "brief" in out.lower() or "concise" in out.lower()
    assert source.startswith("builtin"), f"source={source}"
    # "default" is a no-op
    out_default, _ = OS.apply_to_system_instruction(base, "default", cwd)
    assert out_default == base, "default should not modify base"
print("[PASS] apply_to_system_instruction appends overlay with header")


# ===========================================================================
# Test 3: project-level custom style overrides built-in
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    styles_dir = cwd / ".open-code" / "output-styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "concise.md").write_text(
        "USE ALL CAPS FOR EMPHASIS.", encoding="utf-8",
    )
    overlay, source = OS.resolve_overlay("concise", cwd)
    assert "ALL CAPS" in overlay
    assert source.startswith("project:")
print("[PASS] project-level custom style overrides built-in name")


# ===========================================================================
# Test 4: unknown style is a silent no-op (no crash, empty overlay)
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    overlay, source = OS.resolve_overlay("does-not-exist", cwd)
    assert overlay == ""
    assert source.startswith("unknown:")
    out, _ = OS.apply_to_system_instruction("base", "does-not-exist", cwd)
    assert out == "base"  # unchanged because overlay was empty
print("[PASS] unknown style is a no-op")


# ===========================================================================
# Test 5: list_available reports project styles even with same name as builtin
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    styles_dir = cwd / ".open-code" / "output-styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "concise.md").write_text("...", encoding="utf-8")
    (styles_dir / "mystyle.md").write_text("...", encoding="utf-8")
    rows = OS.list_available(cwd)
    by_name = {name: source for name, source in rows}
    assert by_name["mystyle"] == "project"
    assert by_name["concise"] == "project"  # project overrode builtin label
    assert by_name["explanatory"] == "builtin"  # still builtin
    assert by_name["default"] == "builtin"
print("[PASS] list_available labels project styles as 'project'")


# ===========================================================================
# Test 6: settings.output_style read from settings.json
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    proj = cwd / ".open-code"
    proj.mkdir()
    (proj / "settings.json").write_text(json.dumps({
        "output_style": "explanatory",
    }), encoding="utf-8")
    s = S.load_layered_settings(cwd)
    assert s.output_style == "explanatory", \
        f"expected output_style='explanatory'; got {s.output_style!r}"
print("[PASS] settings.output_style honored from settings.json")


# ===========================================================================
# Test 7: settings.output_style defaults to 'default' when missing
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    s = S.load_layered_settings(cwd)
    assert s.output_style == "default"
print("[PASS] settings.output_style defaults to 'default'")


print("\nOK -- output-styles probes passed.")
