"""Probe: plugin system (Tier 2 #22).

Plugins live at <cwd>/.open-code/plugins/<name>/ or
~/.open-code/plugins/<name>/. Each has a plugin.json manifest and
exposes skills / agents / output styles under conventional paths.

Tests:
  1. discover_plugins parses a valid plugin.json
  2. Invalid / missing manifest -> skipped silently
  3. Project plugin overrides same-name user plugin
  4. Plugin-provided skill shows up in skills.discover_skills
  5. Local skill with same name beats plugin skill
  6. Plugin-provided output style is resolvable
  7. Project output style overrides plugin output style
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import plugins as P
import skills as SK
import output_styles as OS


def _make_plugin(parent: Path, name: str, manifest: dict,
                 skills_map: dict[str, str] | None = None,
                 styles_map: dict[str, str] | None = None) -> Path:
    pdir = parent / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    for skill_name, body in (skills_map or {}).items():
        d = pdir / "skills" / skill_name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(body, encoding="utf-8")
    for style_name, body in (styles_map or {}).items():
        d = pdir / "output-styles"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{style_name}.md").write_text(body, encoding="utf-8")
    return pdir


# ===========================================================================
# Test 1: discover_plugins parses a valid manifest
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    plugins_root = base / ".open-code" / "plugins"
    _make_plugin(plugins_root, "alpha", {
        "name": "alpha",
        "version": "1.2.0",
        "description": "Test plugin",
        "exposes": {"skills": ["one"], "output_styles": ["mood"]},
    })
    # Need to mock USER_PLUGINS_DIR away to ensure we don't pick up
    # the user's real plugins
    with patch.object(P, "USER_PLUGINS_DIR", base / "no-such-dir"):
        ps = P.discover_plugins(base)
    assert len(ps) == 1
    assert ps[0].name == "alpha"
    assert ps[0].version == "1.2.0"
    assert ps[0].source == "project"
    assert ps[0].exposes_skills == ["one"]
    assert ps[0].exposes_output_styles == ["mood"]
print("[PASS] discover_plugins parses a valid plugin.json")


# ===========================================================================
# Test 2: invalid manifest -> skipped silently
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    pr = base / ".open-code" / "plugins" / "broken"
    pr.mkdir(parents=True)
    (pr / "plugin.json").write_text("not json {", encoding="utf-8")
    # Another with no manifest at all
    (base / ".open-code" / "plugins" / "no-manifest").mkdir(parents=True)
    with patch.object(P, "USER_PLUGINS_DIR", base / "no-such-dir"):
        ps = P.discover_plugins(base)
    assert ps == [], f"expected empty list; got {ps}"
print("[PASS] invalid/missing manifest is silently skipped")


# ===========================================================================
# Test 3: project plugin overrides same-name user plugin
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    user_root = base / "user-plugins"
    proj_root = base / ".open-code" / "plugins"
    _make_plugin(user_root, "shared", {
        "name": "shared", "version": "USER-version",
    })
    _make_plugin(proj_root, "shared", {
        "name": "shared", "version": "PROJECT-version",
    })
    with patch.object(P, "USER_PLUGINS_DIR", user_root):
        ps = P.discover_plugins(base)
    assert len(ps) == 1
    assert ps[0].version == "PROJECT-version"
    assert ps[0].source == "project"
print("[PASS] project plugin overrides same-name user plugin")


# ===========================================================================
# Test 4: plugin-provided skill shows up in skills.discover_skills
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj_root = base / ".open-code" / "plugins"
    _make_plugin(proj_root, "alpha", {
        "name": "alpha", "version": "1.0",
        "exposes": {"skills": ["greet"]},
    }, skills_map={
        "greet": "---\nname: greet\n---\nHello, $ARGUMENTS!\n",
    })
    with patch.object(P, "USER_PLUGINS_DIR", base / "no-such-dir"):
        SK.clear_skill_cache()
        all_skills = SK.discover_skills(base)
    names = {s.name for s in all_skills}
    assert "greet" in names, f"plugin skill missing from {names}"
print("[PASS] plugin-provided skill discovered by skills.discover_skills")


# ===========================================================================
# Test 5: local skill with same name overrides plugin skill
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj_plugin = base / ".open-code" / "plugins"
    _make_plugin(proj_plugin, "alpha", {
        "name": "alpha", "version": "1.0",
        "exposes": {"skills": ["greet"]},
    }, skills_map={
        "greet": "---\nname: greet\n---\nFROM-PLUGIN\n",
    })
    # Local skill with same name
    local_skill = base / ".open-code" / "skills" / "greet"
    local_skill.mkdir(parents=True)
    (local_skill / "SKILL.md").write_text(
        "---\nname: greet\n---\nFROM-LOCAL\n", encoding="utf-8",
    )
    with patch.object(P, "USER_PLUGINS_DIR", base / "no-such-dir"):
        SK.clear_skill_cache()
        sk = SK.find_skill_by_name(base, "greet")
    assert sk is not None
    assert "FROM-LOCAL" in sk.body, f"local should win; body={sk.body!r}"
    assert "FROM-PLUGIN" not in sk.body
print("[PASS] local skill overrides plugin skill of same name")


# ===========================================================================
# Test 6: plugin output style is resolvable
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj_plugin = base / ".open-code" / "plugins"
    _make_plugin(proj_plugin, "alpha", {
        "name": "alpha", "version": "1.0",
        "exposes": {"output_styles": ["mood"]},
    }, styles_map={
        "mood": "BE SOMBER.",
    })
    with patch.object(P, "USER_PLUGINS_DIR", base / "no-such-dir"):
        overlay, source = OS.resolve_overlay("mood", base)
    assert overlay == "BE SOMBER."
    assert source == "plugin:alpha"
print("[PASS] plugin-provided output style is resolvable")


# ===========================================================================
# Test 7: project style overrides plugin style of same name
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj_plugin = base / ".open-code" / "plugins"
    _make_plugin(proj_plugin, "alpha", {
        "name": "alpha", "version": "1.0",
        "exposes": {"output_styles": ["mood"]},
    }, styles_map={"mood": "FROM-PLUGIN"})
    # Project-level style overrides
    proj_styles = base / ".open-code" / "output-styles"
    proj_styles.mkdir(parents=True)
    (proj_styles / "mood.md").write_text("FROM-PROJECT", encoding="utf-8")
    with patch.object(P, "USER_PLUGINS_DIR", base / "no-such-dir"):
        overlay, source = OS.resolve_overlay("mood", base)
    assert overlay == "FROM-PROJECT"
    assert source.startswith("project:")
print("[PASS] project style overrides plugin style of same name")


print("\nOK -- plugins probes passed.")
